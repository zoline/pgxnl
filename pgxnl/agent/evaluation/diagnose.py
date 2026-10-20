"""오답 카테고리 진단 (docs/pgxnl_antlr_pipeline_design.md §3.2, §6).

이미 저장된 평가 결과(pgxnl_eval_items)의 pred/gold SQL을 파싱해 구조적으로 비교하고,
오답을 카테고리로 분류한다. **DB를 다시 실행하지 않는다** — 파싱과 IR 비교만 하므로
과거 run에 대해서도 즉시 돌릴 수 있다.

설계 문서 §7이 제안한 순서(visitor -> 성공률 측정 -> compare_ir -> 카테고리 통계)와
달리, 여기서는 카테고리 통계를 먼저 낼 수 있게 묶었다. §6이 "카테고리별 분포 산출이
다음 단계의 최우선 작업"이라고 못박았는데, 그 진단이 나오기 전에 무엇을 더 지을지
결정할 수 없기 때문이다.

사용:
    python -m pgxnl.agent.evaluation.diagnose <run_id>
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field

from pgxnl.parsing.base import SqlParser
from pgxnl.parsing.ir import QueryIR
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

# --- 카테고리 (§6) --------------------------------------------------------
# 문서 §6의 7개에 더해 NO_SQL / ORDER_LIMIT_MISMATCH / UNCOMPARABLE / GOLD_UNPARSEABLE을
# 두었다. 앞의 셋은 실제 결과셋에서 분리해두지 않으면 SEMANTIC_WRONG에 섞여 들어가
# "진짜 논리 오류" 비중을 부풀린다.
MATCH = "MATCH"
NO_SQL = "NO_SQL"  # 모델이 SQL 자체를 못 냄 (도구 실패/최대 반복 초과)
SYNTAX = "SYNTAX"
PROJECTION_MISMATCH = "PROJECTION_MISMATCH"
PREDICATE_MISMATCH = "PREDICATE_MISMATCH"
JOIN_MISMATCH = "JOIN_MISMATCH"
GROUPBY_MISMATCH = "GROUPBY_MISMATCH"
ORDER_LIMIT_MISMATCH = "ORDER_LIMIT_MISMATCH"
# 절 구조는 gold와 완전히 같은데 실행 결과만 다른 경우. 리터럴 값, 타입 캐스팅,
# 조인 카디널리티(중복 행) 같은 원인이며 **구조 비교로는 잡을 수 없다**.
# SEMANTIC_WRONG(여러 절이 어긋난 진짜 논리 오류)과 섞으면 개선 방향이 정반대로 나온다.
VALUE_MISMATCH = "VALUE_MISMATCH"
SEMANTIC_WRONG = "SEMANTIC_WRONG"
UNCOMPARABLE = "UNCOMPARABLE"  # 서브쿼리/집합연산 — 절 단위 비교를 신뢰할 수 없음
GOLD_UNPARSEABLE = "GOLD_UNPARSEABLE"  # gold를 못 읽음 = 하네스 쪽 문제


@dataclass
class StructuralDiff:
    """절 그룹별 일치 여부. 어느 절이 틀렸는지가 카테고리를 결정한다."""

    projection: bool = True
    predicate: bool = True
    join: bool = True
    group_by: bool = True
    order_limit: bool = True
    comparable: bool = True

    def mismatched(self) -> list[str]:
        out = []
        if not self.projection:
            out.append(PROJECTION_MISMATCH)
        if not self.predicate:
            out.append(PREDICATE_MISMATCH)
        if not self.join:
            out.append(JOIN_MISMATCH)
        if not self.group_by:
            out.append(GROUPBY_MISMATCH)
        if not self.order_limit:
            out.append(ORDER_LIMIT_MISMATCH)
        return out


@dataclass
class Diagnosis:
    seq: int
    category: str
    detail: str = ""
    difficulty: str = ""


# --- 절 비교 (§3.2) -------------------------------------------------------


def _predicate_signatures(node) -> set[str]:
    """AND로 묶인 조건들을 잎 집합으로 편다. OR 하위는 통째로 하나의 잎."""
    if node is None:
        return set()
    return {leaf.signature() for leaf in node.flatten_and()}


def _tables_of(ir: QueryIR) -> set[str]:
    """기본 테이블과 조인 대상을 하나의 집합으로 본다.

    `FROM u JOIN t`와 `FROM t JOIN u`는 같은 질의인데 어느 쪽이 기본 테이블인지만
    다르다 — 나눠서 비교하면 동치를 오답으로 잡는다.
    """
    return set(ir.from_tables) | {j.table for j in ir.joins}


def _join_conditions(ir: QueryIR) -> set[tuple[str, str]]:
    """(조인 타입, 조인 조건) 집합. 조인 대상 테이블명은 _tables_of가 이미 보므로
    여기서 빼야 조인 순서 뒤바뀜에 흔들리지 않는다."""
    out = set()
    for j in ir.joins:
        cond = j.on.signature() if j.on else ",".join(sorted(j.using))
        out.add((j.join_type, cond))
    return out


def compare_ir(pred: QueryIR, gold: QueryIR) -> StructuralDiff:
    diff = StructuralDiff()

    # 서브쿼리/집합연산이 한쪽이라도 있으면 절 단위 비교가 성립하지 않는다(§8).
    if not (pred.is_simple and gold.is_simple):
        diff.comparable = False
        return diff

    # SELECT: alias는 무시하고 표현식 집합으로 비교 (§3.2)
    diff.projection = {i.expr for i in pred.select_items} == {i.expr for i in gold.select_items}

    diff.predicate = _predicate_signatures(pred.where) == _predicate_signatures(gold.where) and (
        _predicate_signatures(pred.having) == _predicate_signatures(gold.having)
    )

    diff.join = _tables_of(pred) == _tables_of(gold) and _join_conditions(pred) == _join_conditions(gold)

    diff.group_by = set(pred.group_by) == set(gold.group_by)

    # gold에 ORDER BY가 없으면 pred의 정렬 차이는 무시한다 (§3.2)
    if not gold.order_by:
        diff.order_limit = pred.limit == gold.limit
    else:
        diff.order_limit = pred.order_by == gold.order_by and pred.limit == gold.limit

    return diff


def classify(diff: StructuralDiff) -> str:
    """틀린 절이 하나면 그 카테고리, 여럿이면 논리 오류로 본다 (§6)."""
    if not diff.comparable:
        return UNCOMPARABLE
    wrong = diff.mismatched()
    if not wrong:
        return VALUE_MISMATCH
    if len(wrong) == 1:
        return wrong[0]
    return SEMANTIC_WRONG


# --- 문항 단위 진단 -------------------------------------------------------


def diagnose_item(
    parser: SqlParser, *, seq: int, gold_sql: str, pred_sql: str | None,
    ex_pass: bool | None, difficulty: str = "",
) -> Diagnosis:
    if ex_pass:
        return Diagnosis(seq=seq, category=MATCH, difficulty=difficulty)

    if not (pred_sql or "").strip():
        return Diagnosis(seq=seq, category=NO_SQL, difficulty=difficulty)

    try:
        pred_ir = parser.to_ir(parser.parse(pred_sql))
    except Exception as exc:  # noqa: BLE001 — 파싱 실패 자체가 진단 결과다
        return Diagnosis(seq=seq, category=SYNTAX, detail=str(exc)[:200], difficulty=difficulty)
    if pred_ir is None:
        return Diagnosis(seq=seq, category=SYNTAX, detail="SELECT로 파싱되지 않음", difficulty=difficulty)

    try:
        gold_ir = parser.to_ir(parser.parse(gold_sql))
    except Exception as exc:  # noqa: BLE001
        return Diagnosis(seq=seq, category=GOLD_UNPARSEABLE, detail=str(exc)[:200], difficulty=difficulty)
    if gold_ir is None:
        return Diagnosis(seq=seq, category=GOLD_UNPARSEABLE, difficulty=difficulty)

    diff = compare_ir(pred_ir, gold_ir)
    return Diagnosis(
        seq=seq, category=classify(diff), detail=",".join(diff.mismatched()), difficulty=difficulty
    )


@dataclass
class RunReport:
    total: int = 0
    counts: Counter = field(default_factory=Counter)
    by_difficulty: dict[str, Counter] = field(default_factory=dict)
    diagnoses: list[Diagnosis] = field(default_factory=list)

    def add(self, d: Diagnosis) -> None:
        self.total += 1
        self.counts[d.category] += 1
        self.by_difficulty.setdefault(d.difficulty or "-", Counter())[d.category] += 1
        self.diagnoses.append(d)

    def render(self) -> str:
        lines = [f"총 {self.total}문항", ""]
        width = max((len(c) for c in self.counts), default=10)
        for category, n in self.counts.most_common():
            pct = 100.0 * n / self.total if self.total else 0.0
            bar = "█" * int(pct / 2)
            lines.append(f"  {category:<{width}}  {n:>4}  {pct:5.1f}%  {bar}")
        wrong = self.total - self.counts.get(MATCH, 0)
        if wrong:
            unusable = self.counts.get(SYNTAX, 0) + self.counts.get(NO_SQL, 0)
            lines += ["", f"오답 {wrong}건 중 SQL을 못 쓴 것(SYNTAX+NO_SQL): {unusable}건"]
        return "\n".join(lines)


def diagnose_items(items: list) -> RunReport:
    """EvalItem 유사 객체(seq/gold_sql/pred_sql/ex_pass/difficulty)의 리스트를 진단한다."""
    parser = AntlrPostgresParser()
    report = RunReport()
    for it in items:
        report.add(
            diagnose_item(
                parser,
                seq=getattr(it, "seq", 0),
                gold_sql=getattr(it, "gold_sql", "") or "",
                pred_sql=getattr(it, "pred_sql", None),
                ex_pass=getattr(it, "ex_pass", None),
                difficulty=getattr(it, "difficulty", "") or "",
            )
        )
    return report


async def _main(run_id: int) -> None:
    import asyncpg

    from pgxnl.agent.evaluation.store import EvalStore
    from pgxnl.settings import Settings

    settings = Settings()
    pool = await asyncpg.create_pool(settings.system_pg_dsn, min_size=1, max_size=2)
    try:
        store = EvalStore(pool)
        run = await store.get_run(run_id)
        if run is None:
            print(f"run {run_id}을 찾을 수 없습니다.")
            return
        items: list = []
        offset = 0
        while True:
            page = await store.get_items(run_id, limit=500, offset=offset)
            if not page:
                break
            items.extend(page)
            offset += len(page)
        # ex_pct는 @property다 — 호출하면 TypeError가 난다.
        print(f"run {run_id} ({getattr(run, 'run_name', '')}) — EX {run.ex_pct:.1f}%\n")
        print(diagnose_items(items).render())
    finally:
        await pool.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python -m pgxnl.agent.evaluation.diagnose <run_id>")
        raise SystemExit(1)
    asyncio.run(_main(int(sys.argv[1])))

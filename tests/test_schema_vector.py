"""스키마 벡터 검색 결과 컷오프(filter_by_score_margin) 단위 테스트. design 문서 §5.4 참고.

배경: top_k만으로는 관련성을 보장하지 못해(예: 24개 테이블 스키마에서 top_k=10이면
질문과 무관한 테이블도 절반 가까이 그대로 채워짐), 실제 dvdrental 대상으로 측정한
코사인 점수를 근거로 마진 기반 컷오프를 추가했다. 실측 점수 분포가 좁아서(0.48~0.58대)
margin이 너무 작으면 정답 테이블까지 잘릴 수 있다는 걸 이 테스트에서도 재현해둔다.
"""
from pgxnl.cache.schema_vector import SchemaVectorIndex, TableCandidate, filter_by_score_margin
from pgxnl.connectors.base import ColumnMeta, TableMeta


def _candidates(*scores: float) -> list[TableCandidate]:
    return [
        TableCandidate(schema="public", table=f"t{i}", mschema="", score=s)
        for i, s in enumerate(scores)
    ]


def test_margin_zero_keeps_everything_unchanged():
    candidates = _candidates(0.58, 0.55, 0.52, 0.51)

    result = filter_by_score_margin(candidates, 0.0)

    assert result == candidates


def test_margin_drops_candidates_below_top_score_minus_margin():
    candidates = _candidates(0.58, 0.56, 0.50, 0.48)

    result = filter_by_score_margin(candidates, 0.05)

    assert [c.score for c in result] == [0.58, 0.56]


def test_margin_always_keeps_top_candidate_even_if_alone():
    candidates = _candidates(0.58, 0.30, 0.20)

    result = filter_by_score_margin(candidates, 0.01)

    assert [c.score for c in result] == [0.58]


def test_empty_candidates_returns_empty():
    assert filter_by_score_margin([], 0.05) == []


def test_realistic_dvdrental_scores_keep_relevant_table_within_default_margin():
    # 실측: "제일 잘 나가는 배우가 누구야?" 질문에서 정답 테이블(actor)이 1위가 아니라
    # 9위(0.5127)로 나왔다 — customer(0.5454)가 오히려 1위. 기본 마진(0.05)이 이
    # 실측 케이스에서 actor를 잘라내지 않는지 확인한다(너무 타이트하면 정답이 잘림).
    candidates = _candidates(
        0.5454,  # customer
        0.5301,  # film_category
        0.5266,  # address
        0.5248,  # category
        0.5197,  # language
        0.5196,  # film_actor
        0.5164,  # film
        0.5145,  # store
        0.5127,  # actor <- 정답 테이블
        0.5089,  # inventory
        0.4869,  # staff
    )

    result = filter_by_score_margin(candidates, 0.05)

    kept_scores = {c.score for c in result}
    assert 0.5127 in kept_scores  # actor가 살아남아야 함
    assert 0.4869 not in kept_scores  # staff처럼 명백히 먼 후보는 잘려야 함


class _FakePool:
    def __init__(self):
        self.executed: list[tuple] = []

    async def execute(self, query, *args):
        self.executed.append(args)


def _table(name: str) -> TableMeta:
    return TableMeta(
        schema="public", name=name, comment=None,
        columns=[ColumnMeta(name="id", data_type="integer")], foreign_keys=[],
    )


async def test_build_all_skips_failed_table_and_continues():
    # 실제로 겪은 회귀: BIRD 재구축 중 컬럼이 매우 많은 테이블 하나가 임베딩 모델의
    # 최대 시퀀스 길이를 넘겨 500 오류를 냈는데, 당시엔 build_all() 전체가 죽어서
    # 그 뒤에 오는 스키마들이 아예 재색인되지 않았다(75개 중 24개에서 멈춤). 테이블
    # 하나가 실패해도 나머지는 계속 처리돼야 한다.
    calls: list[str] = []

    async def embed_fn(text: str) -> list[float]:
        calls.append(text)
        if "bad" in text:
            raise RuntimeError("Token sequence length exceeds the maximum sequence length")
        return [0.1, 0.2]

    pool = _FakePool()
    index = SchemaVectorIndex(pool, embed_fn, "target")

    succeeded = await index.build_all([_table("good1"), _table("bad"), _table("good2")])

    assert succeeded == 2  # 실패한 테이블 제외하고 성공 수를 반환
    assert len(calls) == 3  # 세 테이블 다 시도는 됨(중간에 멈추지 않음)
    assert len(pool.executed) == 2  # 실패한 테이블은 DB에 쓰지 않음


async def test_index_table_returns_false_on_embedding_failure():
    async def failing_embed_fn(text: str) -> list[float]:
        raise RuntimeError("boom")

    pool = _FakePool()
    index = SchemaVectorIndex(pool, failing_embed_fn, "target")

    ok = await index.index_table(_table("t1"))

    assert ok is False
    assert pool.executed == []

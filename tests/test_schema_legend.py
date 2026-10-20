"""스키마 컨텍스트 섹션 설명 (2026-10-14)."""
from pgxnl.agent.orchestrator import _schema_legend


def test_있는_섹션만_설명한다():
    out = _schema_legend("# Table: t\n【Foreign keys】\nt.a=u.id\n[용어집]\nx: y")
    assert "【Foreign keys】:" in out and "[용어집]: 질문 표현" in out and "【Join paths】" not in out
    assert out.endswith("\n\n")


def test_섹션이_없으면_빈_문자열():
    assert _schema_legend("# Table: t\n[\n  (id, bigint, PK),\n]") == ""

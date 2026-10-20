# ANTLR4 PostgreSQL Grammar

이 디렉토리는 ANTLR4로 생성된 PostgreSQL 파서 코드(`*.g4` → 생성된 Lexer/Parser/Visitor)를
보관합니다. 생성 코드는 저장소에 커밋하지 않고(용량/버전 관리 문제), 빌드 시점에
생성하는 것을 권장합니다.

## 권장 grammar

커뮤니티에서 유지보수되는 PostgreSQL grammar를 기반으로 시작하는 것을 권장합니다
(예: `antlr/grammars-v4` 저장소의 `sql/postgresql` grammar). 자체 요구사항(예:
JSON 연산자, 윈도우 함수 등)에 맞춰 필요한 부분만 커스터마이즈합니다.

## 생성 명령 예시

```bash
antlr4 -Dlanguage=Python3 -visitor -o pgxnl/grammar/generated PostgreSQLLexer.g4 PostgreSQLParser.g4
```

## 향후 확장 (ADR-0001, ADR-0002 참고)

다른 DBMS를 다시 지원하게 되면, 이 디렉토리에 `oracle/`, `mysql/` 같은 하위
디렉토리를 추가하고 `pgxnl/parsing/`에 대응하는 파서 래퍼를 추가하는 방식으로
확장합니다. `pgxnl/agent/canonicalize.py`, `pgxnl/agent/validation.py`,
`pgxnl/agent/discovery/join_history.py`는 `pgxnl/parsing`의 공통 인터페이스만
사용하므로 grammar 교체와 독립적으로 동작합니다.

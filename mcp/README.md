# pgxnl-mcp

외부 agent(Claude Code, Claude Desktop 등)가 pgxnl 을 MCP 도구로 쓰게 하는 얇은 다리.
DB 에 직접 붙지 않고 pgxnl HTTP API 를 API 키로 부른다 — 읽기 전용·비용 상한·감사 기록이
웹 화면과 똑같이 적용된다.

역할 분담: pgxnl 이 SQL 생성·검증·실행까지 하고, 결과 해석·요약은 MCP 클라이언트 LLM 이 한다.
그래서 `ask` 는 pgxnl 의 요약 단계를 건너뛰고 SQL 과 결과 행을 돌려준다.

## 도구

| 도구 | 하는 일 |
|---|---|
| `list_targets` | 질의할 수 있는 대상 DB 목록 |
| `list_schemas` | 대상 DB 의 스키마 목록 |
| `describe_schema` | 테이블·컬럼(타입·PK·FK·주석). `search`·`schema` 로 좁힌다 |
| `ask` | 자연어 질문 → SQL + 결과 행. `sql_only=true` 면 실행 없이 SQL 만 |
| `run_sql` | SQL 을 pgxnl 검증 계층을 거쳐 실행 |
| `explain` | 실행계획(EXPLAIN FORMAT JSON, 선택적으로 ANALYZE) |
| `find_join_path` | 두 테이블을 잇는 JOIN 경로(승인된 관계만) |
| `similar_queries` | 승인된 검증 질의 중 비슷한 것 |

`ask` 는 질문 하나에 수십 초~1분 이상 걸린다(진행 상황은 MCP 로그 알림으로 보낸다).

## 준비

1. pgxnl 관리 화면 → 사용자에서 MCP 용 사용자(역할 `user`)를 만들고 API 키를 받는다.
2. pgxnl 서버 주소가 DNS 에 없으면 클라이언트 PC 의 hosts 에 등록한다.
   ```
   203.0.113.10   pgxnl.example.com
   ```

## 설치

```bash
pipx install "git+https://github.com/zoline/pgxnl.git#subdirectory=mcp"
```

## 환경변수

| 변수 | 설명 |
|---|---|
| `PGXNL_URL` | pgxnl 주소, 예: `https://pgxnl.example.com` (필수) |
| `PGXNL_API_KEY` | pgxnl API 키 (필수) |
| `PGXNL_VERIFY_SSL` | `false` 면 인증서 검증을 끈다 — 자체 서명 인증서일 때만. 기본 `true` |
| `PGXNL_MCP_MAX_ROWS` | 클라이언트에 넘길 최대 행 수. 기본 50 |
| `PGXNL_MCP_MAX_CHARS` | 결과 JSON 최대 글자 수(넓은 행 대비). 기본 20000 |

## 클라이언트 등록

Claude Code:
```bash
claude mcp add pgxnl \
  -e PGXNL_URL=https://pgxnl.example.com \
  -e PGXNL_API_KEY=<API 키> \
  -- pgxnl-mcp
```

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "pgxnl": {
      "command": "pgxnl-mcp",
      "env": { "PGXNL_URL": "https://pgxnl.example.com", "PGXNL_API_KEY": "<API 키>" }
    }
  }
}
```

API 키는 그 사용자의 권한 그대로 쓰인다 — 키를 공유하지 말고 사용자(또는 agent)마다 따로 발급한다.

## 개발

```bash
cd mcp
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

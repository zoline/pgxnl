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
| `PGXNL_SERVER_NAME` | URL 을 IP 로 줄 때 인증서 검증·SNI·Host 에 쓸 이름. hosts 를 고칠 수 없는 곳(컨테이너 안 등)용 — 예: `PGXNL_URL=https://203.0.113.10`, `PGXNL_SERVER_NAME=pgxnl.example.com` |
| `PGXNL_VERIFY_SSL` | `false` 면 인증서 검증을 끈다 — 자체 서명 인증서일 때만. 기본 `true` |
| `PGXNL_MCP_MAX_ROWS` | 클라이언트에 넘길 최대 행 수. 기본 50 |
| `PGXNL_MCP_MAX_CHARS` | 결과 JSON 최대 글자 수(넓은 행 대비). 기본 20000 |

## 클라이언트 등록

키를 클라이언트 설정 파일에 평문으로 남기지 않으려면 `--env-file` 을 쓴다(권장).
```bash
mkdir -p ~/.config/pgxnl-mcp && chmod 700 ~/.config/pgxnl-mcp
printf 'PGXNL_URL=https://pgxnl.example.com\nPGXNL_API_KEY=<API 키>\n' > ~/.config/pgxnl-mcp/env
chmod 600 ~/.config/pgxnl-mcp/env

claude mcp add -s user pgxnl -- pgxnl-mcp --env-file ~/.config/pgxnl-mcp/env
```
이미 설정된 환경변수가 파일보다 우선한다.

환경변수로 직접 넘기는 방법 — Claude Code:
```bash
claude mcp add pgxnl \
  -e PGXNL_URL=https://pgxnl.example.com \
  -e PGXNL_API_KEY=<API 키> \
  -- pgxnl-mcp
```

Claude Desktop (`claude_desktop_config.json`) — `--env-file` 경로는 절대 경로로:
```json
{
  "mcpServers": {
    "pgxnl": {
      "command": "pgxnl-mcp",
      "args": ["--env-file", "/home/<사용자>/.config/pgxnl-mcp/env"]
    }
  }
}
```

확인: `claude mcp get pgxnl` 이 `✔ Connected` 면 새 세션에서 "northwind 에서 배송사별 주문 건수 알려줘"처럼 묻는다.

API 키는 그 사용자의 권한 그대로 쓰인다 — 키를 공유하지 말고 사용자(또는 agent)마다 따로 발급한다.

## watsonx Orchestrate (Developer Edition)

Orchestrate 는 MCP 를 자기 VM 안의 도구 실행 컨테이너에서 돌린다. 그래서 호스트의 hosts 파일이나
`~/.bashrc` 가 보이지 않는다 — 값은 **연결(connection)** 로만 넘기고, 이름 해석 대신 IP 로 접속하면서
인증서 검증만 이름으로 한다(`PGXNL_SERVER_NAME`). 연결 값은 Orchestrate DB 에 암호화돼 저장되고
MCP 프로세스를 띄울 때 환경변수로 들어간다.

1. 패키지 폴더 — 소스와 `requirements.txt` 만 둔다(Orchestrate 가 zip 으로 묶어 올리고 컨테이너에서 설치한다):
   ```bash
   mkdir -p ~/pgxnl-mcp-toolkit
   cp -r <pgxnl 저장소>/mcp/src/pgxnl_mcp ~/pgxnl-mcp-toolkit/
   printf 'mcp>=1.20,<2\nhttpx>=0.27\n' > ~/pgxnl-mcp-toolkit/requirements.txt
   ```
2. 연결 — Developer Edition 은 `draft` 환경만 있다:
   ```bash
   orchestrate connections add -a pgxnl
   orchestrate connections configure -a pgxnl --env draft -t team -k key_value
   orchestrate connections set-credentials -a pgxnl --env draft \
     -e "PGXNL_URL=https://203.0.113.10" \
     -e "PGXNL_SERVER_NAME=pgxnl.example.com" \
     -e "PGXNL_API_KEY=<API 키>"
   ```
   대화형 셸에서 치면 키가 셸 기록에 남는다 — 앞에 공백을 두거나(`HISTCONTROL=ignorespace`) 실행 후 기록에서 지운다.
3. toolkit:
   ```bash
   orchestrate toolkits add --kind mcp --name pgxnl \
     --description "PostgreSQL 자연어 질의(pgxnl)" \
     --package-root ~/pgxnl-mcp-toolkit --language python \
     --command "python -m pgxnl_mcp.server" --tools "*" --app-id pgxnl
   orchestrate toolkits list          # pgxnl:ask 등 도구 8개
   ```
4. 에이전트 — 예시 `agent.yaml`:
   ```yaml
   spec_version: v1
   kind: native
   name: pgxnl_analyst
   description: PostgreSQL 데이터 질문을 pgxnl 로 SQL 을 만들어 실행하고 결과를 설명한다
   llm: <orchestrate models list 의 모델>
   style: default
   instructions: |
     데이터 질문은 pgxnl:ask 로 처리한다. 대상 DB 를 모르면 pgxnl:list_targets 로 확인한다.
     ask 가 돌려준 rows 를 근거로 답하고 실행된 SQL 도 보여준다. rows 에 없는 숫자는 지어내지 않는다.
   tools: [pgxnl:list_targets, pgxnl:list_schemas, pgxnl:describe_schema, pgxnl:ask,
           pgxnl:run_sql, pgxnl:explain, pgxnl:find_join_path, pgxnl:similar_queries]
   ```
   ```bash
   orchestrate agents import -f agent.yaml
   orchestrate chat ask -n pgxnl_analyst "northwind 에서 배송사별 주문 건수를 알려줘"
   ```
   `chat ask` 는 첫 답 뒤 대화형 입력을 기다린다 — 스크립트에서 `</dev/null` 로 돌리면 EOF 오류가
   반복되니 출력 앞부분을 본다. 웹 화면(기본 3000 포트)에서 대화해도 된다.

- 키 교체: `set-credentials` 를 다시 실행. 코드 갱신: 폴더를 새로 복사하고 `toolkits add` 를 다시 실행.
- Developer Edition 을 초기화하면 연결·toolkit·에이전트가 모두 사라진다 — 2~4 를 다시 한다.
- 되돌리기: `agents remove -n pgxnl_analyst -k native` → `toolkits remove -n pgxnl` → `connections remove -a pgxnl`.

## 개발

```bash
cd mcp
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

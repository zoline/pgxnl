# data/ — BIRD 평가 데이터

> **License: CC BY-SA 4.0** — 이 폴더의 BIRD 유래 파일은 pgxnl 코드(MIT)와 별개로
> [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) 을 따른다.
> 출처: [BIRD benchmark](https://bird-bench.github.io/) mini-dev, PostgreSQL 판
> ([bird-bench/mini_dev](https://github.com/bird-bench/mini_dev)).
> BIRD 저자들은 이 벤치마크를 "research and healthy application only" 용도로 밝히고 있다.

| 파일 | 내용 |
|---|---|
| `bird_minidev_pg.original.json` | BIRD mini-dev PostgreSQL 판 원본 500문항 (수정 없음) |
| `bird_minidev_pg.json` | pgxnl 평가 중 질문·evidence·gold SQL 을 정정한 판. 평가 기본 데이터셋 |
| `CHANGES.md` | 원본 대비 정정 내역(문항별 전후) |

정정 원칙은 `CHANGES.md` 머리말에 있다. 정정 사유와 근거(데이터 대조 결과)는 시스템 DB 의
`pgxnl_eval_gold_defects` 에 있고, 기준 정보 내보내기(`tools/seed_export.py`)로 `seed/gold_defects.json` 에 함께 배포된다.
`bird_minidev_pg.json` 을 고친 뒤에는 `python tools/bird_changes.py` 로 `CHANGES.md` 를 다시 만든다
(`tools/sync_reference.sh` 가 둘 다 한다).

이 폴더의 파일을 수정·재배포할 때도 CC BY-SA 4.0 과 위 출처 표기를 유지해야 한다.

## 원본과 정정본 점수

정정본으로 채점한 점수는 원본 BIRD 점수와 다르다. 비교가 필요하면 `pgxnl.agent.evaluation.bird`
의 평가를 원본 파일로 다시 돌리면 된다(관리 화면 → BIRD 평가 → 파일 업로드).

## 대상 DB

평가하려면 BIRD 데이터베이스 11개(card_games, california_schools 등)가 PostgreSQL 한 DB 안에
스키마별로 들어 있어야 한다. 준비 방법은 저장소 루트 `README.md` 의 "BIRD 평가" 절을 본다.

## Northwind (`northwind_pg.json`)

`northwind_pg.json` 은 BIRD 가 아니다 — pgxnl 데모용 한글 골든 세트(`docs/northwind_golden_set_v2.md`, 34문항)를
`tools/northwind_dataset.py` 로 평가 형식으로 바꾼 것이다(질문·SQL 만, 데이터는 들어 있지 않다). 날짜는 +28년 옮긴
Northwind DB(2024-07 ~ 2026-05) 기준이다. DB 는 `scripts/load_northwind_db.sh` 가 pthom/northwind_psql 에서 받아 만든다.
준비와 실행은 `docs/INSTALL.md` 6.5 절.

# pgxnl 자연어 질의 테스트 결과 — BIRD mini-dev 82문항

측정일: 2026-10-07 (UTC 08:51~09:21) · 대상: pgxnl 자연어→SQL 질의 파이프라인 · 측정 run: card_games #384, california_schools #385

## 요약

| 항목 | card_games | california_schools |
|---|---|---|
| 문항 수 | 52 | 30 |
| 응답 시간 중앙값 | 13.0초 | 22.9초 |
| 응답 시간 평균 | 18.2초 | 28.2초 |
| 정답률 (공식 BIRD 채점) | 41/52 (78.8%) | 28/30 (93.3%) |
| 동시 질문 수 | 1 | 1 |

## 1. 테스트에 사용한 질문

BIRD mini-dev 벤치마크(PostgreSQL판)의 영어 자연어 질문을 사용했습니다. 문항마다 데이터셋이 제공하는 보조 설명(evidence)이 함께 주어집니다. 전체 질문은 아래 [부록: 82문항 기록](#부록-82문항-기록)에 있습니다.

| 스키마 | 문항 수 | simple | moderate | challenging |
|---|---|---|---|---|
| card_games | 52 | 13 | 33 | 6 |
| california_schools | 30 | 8 | 17 | 5 |
| **합계** | **82** | 21 | 50 | 11 |

## 2. 조회·연산한 데이터 규모

### 대상 테이블 크기

| 스키마 | 테이블 | 행 수 |
|---|---|---|
| card_games | legalities | 427,907 |
| card_games | foreign_data | 229,186 |
| card_games | rulings | 87,769 |
| card_games | cards | 56,822 |
| card_games | set_translations | 1,210 |
| card_games | sets | 551 |
| california_schools | schools | 17,686 |
| california_schools | frpm | 9,986 |
| california_schools | satscores | 2,269 |

### 질문 1건이 다룬 규모

| 지표 | card_games | california_schools |
|---|---|---|
| 참조 테이블 행 수 합 — 중앙값 | 58,032 | 19,955 |
| 참조 테이블 행 수 합 — 최대 | 572,498 | 29,941 |
| 결과 행 수 — 중앙값 | 1 | 1 |
| 결과 행 수 — 최대 | 29,936 | 7,806 |

- **참조 테이블 행 수 합**: 생성된 SQL이 사용한 테이블들의 행 수를 더한 값입니다. 실제로 읽은 행 수의 상한에 가깝습니다(인덱스로 일부만 읽을 수 있습니다).
- **결과 행 수**: 생성된 SQL을 실행해 돌려받은 행 수입니다. 대부분 집계·건수·비율처럼 1행이고, 목록형 질문은 수천~수만 행입니다.

## 3. 질문 1건당 응답 소요 시간

질문을 받은 뒤 SQL을 생성·검증·실행하고 답을 요약하기까지의 전체 시간입니다.

| 지표 | card_games | california_schools |
|---|---|---|
| 최소 | 7.8초 | 10.6초 |
| 중앙값 | 13.0초 | 22.9초 |
| 평균 | 18.2초 | 28.2초 |
| 90% 백분위 | 28.4초 | 46.5초 |
| 최대 | 85.3초 | 84.7초 |
| 전체 실행 시간 | 15분 48초 (52문항) | 14분 7초 (30문항) |

- 응답 시간의 대부분은 LLM 생성 시간입니다. LLM은 자체 서버 1대(NVIDIA L40S 1장, qwen3.8-27b, 단일 요청 기준 초당 약 19토큰)이고, 질문 1건에 LLM 호출이 여러 번 일어납니다(테이블 탐색 → SQL 생성 → 검증 → 답 요약). DB 실행 시간은 이에 비해 작습니다.
- 문항별 시간은 순차 처리된 문항의 완료 시각 차이로 계산했습니다.

## 4. 테스트 당시 동시 접속(동시 질문) 수

- **동시 질문 수: 1** — 평가는 동시성 1로, 질문을 한 번에 하나씩 순서대로 처리했습니다.
- **다른 사용자: 없음** — 측정 시간대의 감사 로그에는 평가 계정의 기록만 있습니다.
- **겹친 평가: 없음** — 두 run은 순서대로 실행됐습니다.

따라서 위 응답 시간은 **부하가 없는 단일 사용자 조건**의 값입니다. 동시 사용자가 늘면 같은 LLM 서버를 나눠 쓰므로 응답 시간이 늘어납니다. 동시 접속 성능은 별도로 측정하지 않았습니다.

## 부록: 82문항 기록

- **seq**: 평가 화면의 문항 번호 / **qid**: BIRD 원본 question_id
- **정답**: pgxnl 채점(중복 행 수까지 비교) / 공식 BIRD 채점(집합 비교). ✓ 맞음, ✗ 틀림
- **응답(초)**: 질문 1건 처리 시간 / **참조 행 수**: 사용한 테이블 행 수 합 / **결과 행**: 실행 결과 행 수

### card_games (52문항, run #384)

| seq | qid | 난이도 | 질문 | 사용 테이블 | 참조 행 수 | 결과 행 | 응답(초) | 정답 (pgxnl / 공식) |
|---|---|---|---|---|---|---|---|---|
| 346 | 340 | simple | Which are the cards that have incredibly powerful foils. | cards | 56,822 | 25,061 | 15.9 | ✓ / ✓ |
| 347 | 341 | simple | What are the borderless cards available without powerful foils? | cards | 56,822 | 72 | 21.8 | ✓ / ✓ |
| 348 | 344 | moderate | List all the mythic rarity print cards banned in gladiator format. | cards, legalities | 484,729 | 5 | 18.3 | ✓ / ✓ |
| 349 | 345 | moderate | For artifact type of cards that do not have multiple faces on the same card, state its legalities status for vintage play format. | cards, legalities | 484,729 | 3 | 12.4 | ✓ / ✓ |
| 350 | 346 | moderate | List all the card id and artist with unknown power which are legal for commander play format. | cards, legalities | 484,729 | 29,936 | 27.8 | ✓ / ✓ |
| 351 | 347 | moderate | Find all cards illustrated by Stephen Daniel and describe the text of the ruling of these cards. State if these cards have missing or degraded properties and values. | cards, rulings | 144,591 | 23 | 32.8 | ✓ / ✓ |
| 352 | 349 | moderate | Name the card and artist with the most ruling information. Also state if the card is a promotional printing. | cards, rulings | 144,591 | 1 | 12.8 | ✗ / ✗ |
| 353 | 352 | moderate | Calculate the percentage of the cards availabe in Chinese Simplified. | foreign_data | 229,186 | 1 | 20.1 | ✗ / ✗ |
| 354 | 356 | simple | How many cards have infinite power? | cards | 56,822 | 1 | 7.8 | ✓ / ✓ |
| 355 | 358 | simple | What is the border color of card "Ancestor's Chosen"? | cards | 56,822 | 1 | 8.2 | ✓ / ✓ |
| 356 | 366 | simple | What is the rule of playing card "Benalish Knight"? | cards, legalities | 484,729 | 32 | 10.5 | ✓ / ✓ |
| 357 | 368 | simple | What is the percentage of borderless cards? | cards | 56,822 | 1 | 8.9 | ✓ / ✓ |
| 358 | 371 | challenging | What is the percentage of cards whose language is French among the Story Spotlight cards? | cards, foreign_data | 286,008 | 1 | 31.1 | ✓ / ✓ |
| 359 | 377 | simple | How many cards with original type of "Summon - Angel" have subtype other than "Angel"? | cards | 56,822 | 1 | 9.8 | ✓ / ✓ |
| 360 | 379 | simple | What are the cards belong to duel deck a? List the ID. | cards | 56,822 | 804 | 15.2 | ✓ / ✓ |
| 361 | 383 | simple | How many of the banned cards are white border? | cards, legalities | 484,729 | 1 | 9.9 | ✓ / ✓ |
| 362 | 391 | moderate | Among the Artifact card names, which are black color and comes with foreign languague translation? | cards, foreign_data | 286,008 | 8 | 18.9 | ✓ / ✓ |
| 363 | 397 | moderate | What is the mana cost of cards with a normal layout, a 2003 frame version, with a black border color, and available in paper and mtgo? | cards | 56,822 | 11,446 | 20.7 | ✓ / ✓ |
| 364 | 402 | moderate | What is the percentage of Story Spotlight cards that do not have a text box? List them by their ID. | cards | 56,822 | 104 | 21.4 | ✗ / ✗ |
| 365 | 405 | moderate | How many Brazilian Portuguese translated sets are inside the Commander block? | set_translations, sets | 1,761 | 1 | 10.4 | ✓ / ✓ |
| 366 | 407 | moderate | Lists all types of cards in German. | cards, foreign_data | 286,008 | 408 | 26.5 | ✗ / ✓ |
| 367 | 408 | moderate | How many unknown power cards contain info about the triggered ability | cards | 56,822 | 1 | 9.3 | ✗ / ✗ |
| 368 | 409 | moderate | Indicates the number of cards with pre-modern format, ruling text "This is a triggered mana ability." that do not have multiple faces. | cards, legalities, rulings | 572,498 | 1 | 12.1 | ✓ / ✓ |
| 369 | 412 | moderate | What is the foreign name of the card in French of type Creature, normal layout and black border color, by artist Matthew D. Wilson? | cards, foreign_data | 286,008 | 0 | 12.3 | ✗ / ✗ |
| 370 | 414 | simple | What language is the set of 180 cards that belongs to the Ravnica block translated into? | set_translations, sets | 1,761 | 10 | 20.5 | ✓ / ✓ |
| 371 | 415 | challenging | What percentage of cards with format commander and legal status do not have a content warning? | cards, legalities | 484,729 | 1 | 15.1 | ✓ / ✓ |
| 372 | 416 | challenging | What percentage of cards without power are in French? | cards, foreign_data | 286,008 | 1 | 38.0 | ✓ / ✓ |
| 373 | 422 | simple | What is the language of the card with the multiverse number 149934? | foreign_data | 229,186 | 1 | 11.8 | ✓ / ✓ |
| 374 | 424 | simple | What proportion of cards do not have a text box with a normal layout? | cards | 56,822 | 1 | 12.0 | ✗ / ✗ |
| 375 | 427 | moderate | What languages are available in the set known as Archenemy on the magic card market and having the code ARC? | set_translations, sets | 1,761 | 10 | 21.9 | ✓ / ✓ |
| 376 | 440 | simple | Which foreign language used by "A Pedra Fellwar"? | foreign_data | 229,186 | 1 | 11.1 | ✓ / ✓ |
| 377 | 459 | moderate | Which card costs more converted mana, "Serra Angel" or "Shrine Keeper"? | cards | 56,822 | 1 | 8.9 | ✓ / ✓ |
| 378 | 462 | moderate | What's the Italian name of the set of cards with "Ancestor's Chosen" is in? | cards, set_translations | 58,032 | 3 | 26.6 | ✗ / ✓ |
| 379 | 465 | moderate | For the set of cards with "Ancestor's Chosen" in it, is there a Korean version of it? | cards, set_translations, sets | 58,583 | 1 | 17.9 | ✗ / ✗ |
| 380 | 466 | moderate | Among the cards in the set "Hauptset Zehnte Edition", how many of them are designed by Adam Rex? | cards, set_translations | 58,032 | 1 | 11.0 | ✓ / ✓ |
| 381 | 468 | moderate | What is the Simplified Chinese translation of the name of the set "Eighth Edition"? | set_translations, sets | 1,761 | 1 | 9.4 | ✓ / ✓ |
| 382 | 469 | moderate | Did the set of cards with "Angel of Mercy" appear on Magic: The Gathering Online? | cards, sets | 57,373 | 15 | 10.8 | ✓ / ✓ |
| 383 | 472 | moderate | Among the sets in the block "Ice Age", how many of them have an Italian translation? | set_translations, sets | 1,761 | 1 | 10.4 | ✓ / ✓ |
| 384 | 473 | moderate | Is the set of cards with Adarkar Valkyrie only available outside the United States? | cards, sets | 57,373 | 5 | 11.5 | ✗ / ✗ |
| 385 | 474 | moderate | Among the sets of cards that have an Italian translation, how many of them have a base set number of under 100? | set_translations, sets | 1,761 | 1 | 22.2 | ✓ / ✓ |
| 386 | 477 | challenging | Which of these artists have designed a card in the set Coldsnap, Jeremy Jarvis, Aaron Miller or Chippy? | cards, sets | 57,373 | 2 | 11.1 | ✓ / ✓ |
| 387 | 479 | moderate | Among the cards with converted mana cost higher than 5 in the set Coldsnap, how many of them have unknown power? | cards, sets | 57,373 | 1 | 12.6 | ✓ / ✓ |
| 388 | 480 | moderate | What is the Italian flavor text of the card "Ancestor's Chosen"? | cards, foreign_data | 286,008 | 2 | 16.7 | ✓ / ✓ |
| 389 | 483 | moderate | Please list the Italian text ruling of all the cards in the set Coldsnap. | cards, foreign_data, rulings, sets | 374,328 | 68 | 85.3 | ✗ / ✗ |
| 390 | 484 | moderate | Please list the Italian names of the cards in the set Coldsnap with the highest converted mana cost. | cards, foreign_data, sets | 286,559 | 12 | 28.4 | ✗ / ✗ |
| 391 | 486 | moderate | What is the percentage of the cards with a converted mana cost of 7 in the set Coldsnap? | cards, sets | 57,373 | 1 | 12.6 | ✓ / ✓ |
| 392 | 487 | challenging | What is the percentage of incredibly powerful cards in the set Coldsnap? | cards, sets | 57,373 | 1 | 13.2 | ✓ / ✓ |
| 393 | 518 | moderate | Which of the play format has the highest number of banned status? Indicate the play format and the names of all the card meet the condition. | cards, legalities | 484,729 | 546 | 30.0 | ✓ / ✓ |
| 394 | 522 | moderate | Which cards are ranked 1st on EDHRec? List all of the cards name and its banned play format. | cards, legalities | 484,729 | 66 | 11.4 | ✗ / ✓ |
| 395 | 528 | challenging | List the names of all the cards in the set Hour of Devastation and find the formats in which these cards are legal. | cards, legalities, sets | 485,280 | 1,890 | 17.0 | ✗ / ✓ |
| 396 | 529 | moderate | Find and list the names of sets which doesn't have Japanese translation but have Korean translation. | set_translations, sets | 1,761 | 0 | 10.1 | ✓ / ✓ |
| 397 | 530 | moderate | List all the frame styles and cards Allen Williams worked on and find any banned cards if there are any. | cards, legalities | 484,729 | 1,031 | 45.5 | ✗ / ✗ |

### california_schools (30문항, run #385)

| seq | qid | 난이도 | 질문 | 사용 테이블 | 참조 행 수 | 결과 행 | 응답(초) | 정답 (pgxnl / 공식) |
|---|---|---|---|---|---|---|---|---|
| 438 | 5 | simple | How many schools with an average score in Math greater than 400 in the SAT test are exclusively virtual? | satscores, schools | 19,955 | 1 | 12.9 | ✓ / ✓ |
| 439 | 11 | simple | Please list the codes of the schools with a total enrollment of over 500. | frpm | 9,986 | 7,806 | 32.5 | ✓ / ✓ |
| 440 | 12 | moderate | Among the schools with an SAT excellence rate of over 0.3, what is the highest eligible free rate for students aged 5-17? | frpm, satscores | 12,255 | 1 | 20.5 | ✓ / ✓ |
| 441 | 17 | simple | Rank schools by their average score in Writing where the score is greater than 499, showing their charter numbers. | satscores, schools | 19,955 | 58 | 35.0 | ✓ / ✓ |
| 442 | 23 | moderate | List the names of schools with more than 30 difference in enrollements between K-12 and ages 5-17? Please also give the full street adress of the schools. | frpm, schools | 27,672 | 1,239 | 43.1 | ✓ / ✓ |
| 443 | 24 | moderate | Give the names of the schools with the percent eligible for free meals in K-12 is more than 0.1 and test takers whose test score is greater than or equal to 1500? | frpm, satscores | 12,255 | 1,167 | 22.5 | ✓ / ✓ |
| 444 | 25 | moderate | Name schools in Riverside which the average of average math score for SAT is grater than 400, what is the funding type of these schools? | frpm, satscores, schools | 29,941 | 6 | 36.9 | ✓ / ✓ |
| 445 | 26 | moderate | State the names and full communication address of high schools in Monterey which has more than 800 free or reduced price meals for ages 5-17? | frpm, schools | 27,672 | 6 | 46.7 | ✓ / ✓ |
| 446 | 27 | moderate | What is the average score in writing for the schools that were opened after 1991 or closed before 2000? List the school names along with the score. Also, list the communication number of the schools if there is any. | satscores, schools | 19,955 | 813 | 46.5 | ✗ / ✗ |
| 447 | 28 | challenging | Consider the average difference between K-12 enrollment and 5-17 enrollment of schools that are locally funded, list the names and DOC type of schools which has a difference above this average. | frpm, schools | 27,672 | 57 | 57.0 | ✓ / ✓ |
| 448 | 31 | moderate | What is the eligible free rate of the 10th and 11th schools with the highest enrolment for students in grades 1 through 12? | frpm | 9,986 | 2 | 16.3 | ✓ / ✓ |
| 449 | 32 | moderate | What is the eligible free or reduced price meal rate for the top 5 schools in grades 1-12 with the highest free or reduced price meal count of the schools with the ownership code 66? | frpm, schools | 27,672 | 5 | 37.7 | ✓ / ✓ |
| 450 | 37 | moderate | What is the complete address of the school with the lowest excellence rate? Indicate the Street, City, State and Zip. | satscores, schools | 19,955 | 1 | 18.6 | ✓ / ✓ |
| 451 | 36 | challenging | Under whose administration is the school with the highest number of students scoring 1500 or more on the SAT? Indicate their full names. | satscores, schools | 19,955 | 1 | 42.2 | ✓ / ✓ |
| 452 | 39 | simple | What is the average number of test takers from Fresno schools that opened between 1/1/1980 and 12/31/1980? | satscores, schools | 19,955 | 1 | 13.6 | ✗ / ✗ |
| 453 | 40 | moderate | What is the telephone number for the school with the lowest average score in reading in Fresno Unified? | satscores, schools | 19,955 | 1 | 13.0 | ✓ / ✓ |
| 454 | 41 | simple | List the names of virtual schools that are among the top 5 in their respective counties based on average reading scores. | satscores, schools | 19,955 | 34 | 23.0 | ✓ / ✓ |
| 455 | 45 | moderate | What is the average writing score of each of the schools managed by Ricci Ulrich? List the schools and the corresponding average writing scores. | satscores, schools | 19,955 | 1 | 24.1 | ✓ / ✓ |
| 456 | 46 | simple | Which state special schools have the highest number of enrollees from grades 1 through 12? | frpm, schools | 27,672 | 1 | 13.1 | ✓ / ✓ |
| 457 | 47 | moderate | What is the monthly average number of schools that opened in Alameda County under the jurisdiction of the Elementary School District in 1980? | schools | 17,686 | 1 | 16.7 | ✓ / ✓ |
| 458 | 48 | moderate | What is the ratio of merged Unified School District schools in Orange County to merged Elementary School District schools? | schools | 17,686 | 1 | 17.4 | ✓ / ✓ |
| 459 | 50 | simple | What is the postal street address for the school with the 7th highest Math average? Indicate the school's name. | satscores, schools | 19,955 | 1 | 14.1 | ✓ / ✓ |
| 460 | 62 | challenging | What is the total number of non-chartered schools in the county of Los Angeles with a percent (%) of eligible free meals for grades 1 through 12 that is less than 0.18%? | frpm, schools | 27,672 | 1 | 16.6 | ✓ / ✓ |
| 461 | 72 | moderate | How many students from the ages of 5 to 17 are enrolled at the State Special School school in Fremont for the 2014-2015 academic year? | frpm, schools | 27,672 | 2 | 30.9 | ✓ / ✓ |
| 462 | 77 | moderate | Which schools served a grade span of Kindergarten to 9th grade in the county of Los Angeles and what is its Percent (%) Eligible FRPM (Ages 5-17)? | frpm, schools | 27,672 | 2 | 31.8 | ✓ / ✓ |
| 463 | 79 | moderate | Between San Diego and Santa Barbara, which county offers the most number of schools that does not offer physical building? Indicate the amount. | schools | 17,686 | 1 | 22.7 | ✓ / ✓ |
| 464 | 82 | simple | What is the grade span offered in the school with the highest longitude? | schools | 17,686 | 1 | 10.6 | ✓ / ✓ |
| 465 | 83 | challenging | Of the schools that offers a magnet program serving a grade span of Kindergarten to 8th grade, how many offers Multiple Provision Types? List the number of cities that offers a Kindergarten to 8th grade span and indicate how many schools are there serving such grade span for each city. | frpm, schools | 27,672 | 1 | 84.7 | ✓ / ✓ |
| 466 | 85 | moderate | What is the Percent (%) Eligible Free (K-12) in the school administered by an administrator whose first name is Alusine. List the district code of the school. | frpm, schools | 27,672 | 1 | 24.9 | ✓ / ✓ |
| 467 | 87 | challenging | What are the valid e-mail addresses of the administrator of the school located in the San Bernardino county, City of San Bernardino City Unified that opened between 1/1/2009 to 12/31/2010 whose school types are public Intermediate/Middle Schools and Unified Schools? | schools | 17,686 | 1 | 21.9 | ✓ / ✓ |

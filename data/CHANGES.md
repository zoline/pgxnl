# BIRD mini-dev (PostgreSQL) 정정 내역

`bird_minidev_pg.json` 은 BIRD mini-dev PostgreSQL 판(`bird_minidev_pg.original.json`)을 pgxnl 평가 중에 정정한 것이다.
정정 원칙: 질문이 맞고 gold SQL 이 틀리면 gold 를 고친다. 질문·evidence 가 성립하지 않거나 오기가 있을 때만 그쪽을 고친다.
질문을 gold 에 맞춰 굽히지 않는다. 해석이 갈리는 문항은 고치지 않는다.

정정 문항 29개 (seq 는 파일 안 위치, 0부터).

| seq | db_id | question_id | 바뀐 항목 |
|---|---|---|---|
| 11 | debit_card_specializing | 1490 | SQL |
| 14 | debit_card_specializing | 1500 | SQL |
| 16 | debit_card_specializing | 1505 | SQL |
| 28 | debit_card_specializing | 1531 | SQL |
| 318 | codebase_community | 586 | SQL |
| 323 | codebase_community | 604 | evidence |
| 327 | codebase_community | 637 | SQL |
| 335 | codebase_community | 682 | SQL |
| 339 | codebase_community | 694 | SQL |
| 344 | codebase_community | 710 | SQL |
| 347 | card_games | 341 | SQL |
| 353 | card_games | 352 | evidence |
| 362 | card_games | 391 | question |
| 364 | card_games | 402 | question, evidence |
| 365 | card_games | 405 | evidence |
| 367 | card_games | 408 | evidence |
| 371 | card_games | 415 | evidence |
| 372 | card_games | 416 | evidence |
| 374 | card_games | 424 | evidence |
| 385 | card_games | 474 | evidence |
| 389 | card_games | 483 | question |
| 391 | card_games | 486 | evidence |
| 396 | card_games | 529 | evidence, SQL |
| 444 | california_schools | 25 | evidence |
| 445 | california_schools | 26 | question, SQL |
| 446 | california_schools | 27 | question |
| 447 | california_schools | 28 | question, evidence |
| 450 | california_schools | 37 | question, evidence, SQL |
| 453 | california_schools | 40 | evidence |

## 항목별 전후

### seq 11 · debit_card_specializing · qid 1490
- **SQL** 원본: `SELECT CAST(SUM(CASE WHEN T2.Consumption > 46.73 THEN 1 ELSE 0 END) AS REAL) * 100 / NULLIF(COUNT(T1.CustomerID), 0) FROM customers AS T1 INNER JOIN yearmonth AS T2 ON T1.CustomerID = T2.CustomerID WHERE T1.Segment = 'LAM'`
- **SQL** 정정: `SELECT CAST(COUNT(DISTINCT CASE WHEN T2.Consumption > 46.73 THEN T1.CustomerID END) AS REAL) * 100 / NULLIF(COUNT(DISTINCT T1.CustomerID), 0) FROM customers AS T1 INNER JOIN yearmonth AS T2 ON T1.CustomerID = T2.CustomerID WHERE T1.Segment = 'LAM'`

### seq 14 · debit_card_specializing · qid 1500
- **SQL** 원본: `SELECT T3.Description FROM transactions_1k AS T1 INNER JOIN yearmonth AS T2 ON T1.CustomerID = T2.CustomerID INNER JOIN products AS T3 ON T1.ProductID = T3.ProductID WHERE T2.Date = '201309'`
- **SQL** 정정: `SELECT DISTINCT T3.Description FROM transactions_1k AS T1 INNER JOIN yearmonth AS T2 ON T1.CustomerID = T2.CustomerID INNER JOIN products AS T3 ON T1.ProductID = T3.ProductID WHERE T2.Date = '201309'`

### seq 16 · debit_card_specializing · qid 1505
- **SQL** 원본: `SELECT COUNT(*) FROM yearmonth AS T1 INNER JOIN customers AS T2 ON T1.CustomerID = T2.CustomerID WHERE T2.Currency = 'EUR' AND T1.Consumption > 1000.00`
- **SQL** 정정: `SELECT COUNT(DISTINCT T2.CustomerID) FROM yearmonth AS T1 INNER JOIN customers AS T2 ON T1.CustomerID = T2.CustomerID WHERE T2.Currency = 'EUR' AND T1.Consumption > 1000.00`

### seq 28 · debit_card_specializing · qid 1531
- **SQL** 원본: `SELECT T2.CustomerID, SUM(T2.Price / NULLIF(T2.Amount, 0)), T1.Currency FROM customers AS T1 INNER JOIN transactions_1k AS T2 ON T1.CustomerID = T2.CustomerID WHERE T2.CustomerID = (SELECT CustomerID FROM yearmonth ORDER BY Consumption DESC NULLS LAST LIMIT 1) GROUP BY T2.CustomerID, T1.Currency`
- **SQL** 정정: `SELECT T1.CustomerID, CAST(SUM(T2.Price) AS REAL) / NULLIF(SUM(T2.Amount), 0), T1.Currency FROM customers AS T1 INNER JOIN transactions_1k AS T2 ON T1.CustomerID = T2.CustomerID GROUP BY T1.CustomerID, T1.Currency ORDER BY SUM(T2.Price) DESC NULLS LAST LIMIT 1`

### seq 318 · codebase_community · qid 586
- **SQL** 원본: `SELECT T3.DisplayName, T1.Title FROM posts AS T1 INNER JOIN votes AS T2 ON T1.Id = T2.PostId INNER JOIN users AS T3 ON T3.Id = T2.UserId WHERE T2.BountyAmount = 50 AND T1.Title LIKE '%variance%'`
- **SQL** 정정: `SELECT T3.DisplayName FROM posts AS T1 INNER JOIN votes AS T2 ON T1.Id = T2.PostId INNER JOIN users AS T3 ON T3.Id = T2.UserId WHERE T2.BountyAmount = 50 AND T1.Title LIKE '%variance%'`

### seq 323 · codebase_community · qid 604
- **evidence** 원본: `creating more than 10 post refers to Count (UserId) > 10; average of the up votes = Divide (Sum(UpVotes), Count (UserId)); average age = Divide (Sum(Age), Count(UserId))`
- **evidence** 정정: `creating more than 10 post refers to Count (UserId) > 10; average of the up votes = AVG(UpVotes); average age = AVG(Age)`

### seq 327 · codebase_community · qid 637
- **SQL** 원본: `SELECT T3.Tags FROM users AS T1 INNER JOIN postHistory AS T2 ON T1.Id = T2.UserId INNER JOIN posts AS T3 ON T3.Id = T2.PostId WHERE T1.DisplayName = 'Mark Meckes' AND T3.CommentCount = 0`
- **SQL** 정정: `SELECT T3.Tags FROM users AS T1 INNER JOIN posts AS T3 ON T1.Id = T3.OwnerUserId WHERE T1.DisplayName = 'Mark Meckes' AND T3.CommentCount = 0`

### seq 335 · codebase_community · qid 682
- **SQL** 원본: `SELECT T2.OwnerUserId, T1.DisplayName FROM users AS T1 INNER JOIN posts AS T2 ON T1.Id = T2.OwnerUserId WHERE TO_CHAR(CAST(T1.CreationDate AS TIMESTAMP), 'YYYY') = '2010' ORDER BY T2.FavoriteCount DESC NULLS LAST LIMIT 1`
- **SQL** 정정: `SELECT T2.Id, T1.DisplayName FROM users AS T1 INNER JOIN posts AS T2 ON T1.Id = T2.OwnerUserId WHERE TO_CHAR(CAST(T2.CreaionDate AS TIMESTAMP), 'YYYY') = '2010' ORDER BY T2.FavoriteCount DESC NULLS LAST LIMIT 1`

### seq 339 · codebase_community · qid 694
- **SQL** 원본: `SELECT T3.Text, T1.DisplayName FROM users AS T1 INNER JOIN posts AS T2 ON T1.Id = T2.OwnerUserId INNER JOIN comments AS T3 ON T2.Id = T3.PostId WHERE T2.Title = 'Analysing wind data with R' ORDER BY T1.CreationDate DESC NULLS LAST LIMIT 10`
- **SQL** 정정: `SELECT T3.Text, T1.DisplayName FROM users AS T1 INNER JOIN comments AS T3 ON T1.Id = T3.UserId INNER JOIN posts AS T2 ON T2.Id = T3.PostId WHERE T2.Title = 'Analysing wind data with R' ORDER BY T3.CreationDate DESC NULLS LAST LIMIT 10`

### seq 344 · codebase_community · qid 710
- **SQL** 원본: `SELECT COUNT(T1.id) FROM comments AS T1 INNER JOIN posts AS T2 ON T1.PostId = T2.Id WHERE T2.CommentCount = 1 AND T2.Score = 0`
- **SQL** 정정: `SELECT COUNT(T1.id) FROM comments AS T1 INNER JOIN posts AS T2 ON T1.PostId = T2.Id WHERE T2.CommentCount = 1 AND T1.Score = 0`

### seq 347 · card_games · qid 341
- **SQL** 원본: `SELECT id FROM cards WHERE borderColor = 'borderless' AND (cardKingdomId IS NULL OR cardKingdomId IS NULL)`
- **SQL** 정정: `SELECT id FROM cards WHERE borderColor = 'borderless' AND (cardKingdomFoilId IS NULL OR cardKingdomId IS NULL)`

### seq 353 · card_games · qid 352
- **evidence** 원본: `Chinese Simplified' is the language; percentage = Divide(Sum(id where language = 'Chinese Simplified'), Count(id)) *100`
- **evidence** 정정: `Chinese Simplified' is the language; percentage = Divide(Count(id) where language = 'Chinese Simplified', Count(id)) *100`

### seq 362 · card_games · qid 391
- **question** 원본: `Among the Artifact cards, which are black color and comes with foreign languague translation?`
- **question** 정정: `Among the Artifact card names, which are black color and comes with foreign languague translation?`

### seq 364 · card_games · qid 402
- **question** 원본: `What is the percentage of Story Spotlight cards that do not have a text box? List them by their ID.`
- **question** 정정: `What is the percentage of Story Spotlight cards that do not have a text box?`
- **evidence** 원본: `Story Spotlight cards that do not have a text box refers to isStorylight = 1 and isTextless = 0; Percentage = DIVIDE(SUM(count(id) where isStorySpotlight = 1 AND isTextless = 0 ), SUM(count(id))) * 100`
- **evidence** 정정: `Story Spotlight cards that do not have a text box refers to isStorySpotlight = 1 and isTextless = 0; Percentage = DIVIDE(SUM(count(id) where isStorySpotlight = 1 AND isTextless = 0 ), SUM(count(id))) * 100`

### seq 365 · card_games · qid 405
- **evidence** 원본: `Commander block refer to block = 'Commander'; sets refer to code = setCode; Portuguese refer to language = 'Portuguese (Brasil)'`
- **evidence** 정정: `Commander block refer to block = 'Commander'; sets refer to code = setCode; Portuguese refer to language = 'Portuguese (Brazil)'`

### seq 367 · card_games · qid 408
- **evidence** 원본: `unknown power cards refers to power is null or power = '*';contain info about the triggered ability refers to text contains 'triggered ability'`
- **evidence** 정정: `unknown power cards refers to power is null or power = '*';contain info about the triggered ability refers to the ruling text contains 'triggered ability'`

### seq 371 · card_games · qid 415
- **evidence** 원본: `do not have a content warning refers to hasContentWarning = 0; percentage refers to DIVIDE(COUNT(hasContentWarning = 0),COUNT(ID))*100 where format = 'commander' AND Status = 'legal';`
- **evidence** 정정: `do not have a content warning refers to hasContentWarning = 0; percentage refers to DIVIDE(COUNT(hasContentWarning = 0),COUNT(ID))*100 where format = 'commander' AND Status = 'Legal';`

### seq 372 · card_games · qid 416
- **evidence** 원본: `in French refers to language = 'French'; cards without power refers to power IS NULL OR power = '*'; percentage = DIVIDE(COUNT(language = 'French' and power is NULL or power = '*'), COUNT( power is NULL or power = '*'))*100`
- **evidence** 정정: `in French refers to language = 'French'; cards without power refers to power IS NULL OR power = '*'; percentage = DIVIDE(COUNT(language = 'French' and power is NULL or power = '*'), COUNT( power is NULL or power = '*'))*100; the percentage is computed over the rows of cards without power, not over the cards themselves`

### seq 374 · card_games · qid 424
- **evidence** 원본: `do not have a text box refers to isTextless = 1; proportion refers to DIVIDE(COUNT(Textless = 1 and layout = 'normal'),COUNT(Textless))*100`
- **evidence** 정정: `do not have a text box refers to isTextless = 1; proportion refers to DIVIDE(COUNT(Textless = 1 and layout = 'normal'),COUNT(*))*100`

### seq 385 · card_games · qid 474
- **evidence** 원본: `Italian translation refers to language = 'Italian'; have a translation means translation is not null; base set number of under 100 refers to baseSetSize < 10`
- **evidence** 정정: `Italian translation refers to language = 'Italian'; have a translation means translation is not null; base set number of under 100 refers to baseSetSize < 100`

### seq 389 · card_games · qid 483
- **question** 원본: `Please list the Italian text ruling of all the cards in the set Coldsnap.`
- **question** 정정: `Please list the Italian text of all the cards in the set Coldsnap.`

### seq 391 · card_games · qid 486
- **evidence** 원본: `converted mana cost of 7 refers to convertedManaCost = 7; card set Coldsnap refers to name = 'Coldsnap'; percentage = DIVIDE(SUM(convertedManaCost = 7), SUM(convertedManaCost))*100`
- **evidence** 정정: `converted mana cost of 7 refers to convertedManaCost = 7; card set Coldsnap refers to name = 'Coldsnap'; percentage = DIVIDE(SUM(convertedManaCost = 7), Count(id))*100`

### seq 396 · card_games · qid 529
- **evidence** 원본: `names of sets refers to name; doesn't have Japanese translation refers to language not like '%Japanese%'; have Korean translation refers to language = 'Korean'`
- **evidence** 정정: `names of sets refers to name; doesn't have Japanese translation refers to the set has no translation with language like '%Japanese%'; have Korean translation refers to language = 'Korean'`
- **SQL** 원본: `SELECT name FROM sets WHERE code IN (SELECT setCode FROM set_translations WHERE language = 'Korean' AND NOT language LIKE '%Japanese%')`
- **SQL** 정정: `SELECT name FROM sets WHERE code IN (SELECT setCode FROM set_translations WHERE language = 'Korean') AND code NOT IN (SELECT setCode FROM set_translations WHERE language LIKE '%Japanese%')`

### seq 444 · california_schools · qid 25
- **evidence** 원본: `Average of average math = sum(average math scores) / count(schools).`
- **evidence** 정정: `Average of average math = sum(average math scores) / count(schools); compute it with GROUP BY per school and filter with HAVING. Riverside here refers to the district name (District Name starts with 'Riverside'), not the county.`

### seq 445 · california_schools · qid 26
- **question** 원본: `State the names and full communication address of high schools in Monterey which has more than 800 free or reduced price meals for ages 15-17?`
- **question** 정정: `State the names and full communication address of high schools in Monterey which has more than 800 free or reduced price meals for ages 5-17?`
- **SQL** 원본: `SELECT T1."School Name", T2.Street, T2.City, T2.State, T2.Zip FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T2.County = 'Monterey' AND T1."Free Meal Count (Ages 5-17)" > 800 AND T1."School Type" = 'High Schools (Public)'`
- **SQL** 정정: `SELECT T1."School Name", T2.Street, T2.City, T2.State, T2.Zip FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T2.County = 'Monterey' AND T1."FRPM Count (Ages 5-17)" > 800 AND T1."School Type" = 'High Schools (Public)'`

### seq 446 · california_schools · qid 27
- **question** 원본: `What is the average score in writing for the schools that were opened after 1991 or closed before 2000? List the school names along with the score. Also, list the communication number of the schools if there is any.`
- **question** 정정: `What is the average score in writing for the schools that were opened after 1991 or closed before 2000? List the school names along with the score if there is any. Also, list the communication number of the schools if there is any.`

### seq 447 · california_schools · qid 28
- **question** 원본: `Consider the average difference between K-12 enrollment and 15-17 enrollment of schools that are locally funded, list the names and DOC type of schools which has a difference above this average.`
- **question** 정정: `Consider the average difference between K-12 enrollment and 5-17 enrollment of schools that are locally funded, list the names and DOC type of schools which has a difference above this average.`
- **evidence** 원본: `Difference between K-12 enrollment and 15-17 enrollment can be computed by `Enrollment (K-12)` - `Enrollment (Ages 5-17)``
- **evidence** 정정: `Difference between K-12 enrollment and 5-17 enrollment can be computed by `Enrollment (K-12)` - `Enrollment (Ages 5-17)``

### seq 450 · california_schools · qid 37
- **question** 원본: `What is the complete address of the school with the lowest excellence rate? Indicate the Street, City, Zip and State.`
- **question** 정정: `What is the complete address of the school with the lowest excellence rate? Indicate the Street, City, State and Zip.`
- **evidence** 원본: `Execellence Rate = NumGE1500 / NumTstTakr; complete address has Street, City, State, Zip code`
- **evidence** 정정: `Execellence Rate = NumGE1500 / NumTstTakr; complete address has Street, City, State, Zip code; only schools whose excellence rate is computable count (NumTstTakr > 0 and NumGE1500 is recorded); if several schools tie, take the one whose school name comes first alphabetically, ignoring rows with no school name`
- **SQL** 원본: `SELECT T2.Street, T2.City, T2.State, T2.Zip FROM satscores AS T1 INNER JOIN schools AS T2 ON T1.cds = T2.CDSCode ORDER BY CAST(T1.NumGE1500 AS REAL) / NULLIF(T1.NumTstTakr, 0) ASC NULLS FIRST LIMIT 1`
- **SQL** 정정: `SELECT T2.Street, T2.City, T2.State, T2.Zip FROM satscores AS T1 INNER JOIN schools AS T2 ON T1.cds = T2.CDSCode WHERE T1.NumTstTakr > 0 AND T1.NumGE1500 IS NOT NULL AND T2.School IS NOT NULL ORDER BY CAST(T1.NumGE1500 AS REAL) / T1.NumTstTakr ASC, T2.School ASC LIMIT 1`

### seq 453 · california_schools · qid 40
- **evidence** 원본: `Fresno Unified is a name of district;`
- **evidence** 정정: `Fresno Unified is a name of district; only schools whose average reading score is recorded count (AvgScrRead is not null)`

# Northwind 골든 세트 v2 — 질문 생성 원칙과 수정 문항

DB 데이터는 변경하지 않았습니다. 질문만 보고 출력 컬럼과 순서를 유추할 수 있도록 아래 원칙으로 문항을 다시 썼습니다. 이 원칙은 Text-to-SQL 모델의 프롬프트(또는 MCP 도구 설명)에 그대로 넣는 것을 전제로 합니다.

## 생성 원칙

- **P1 출력 항목 명시**: 결과로 나올 항목은 질문에 모두 명사로 적는다. 질문에 없는 항목은 내지 않는다.
- **P2 나열 순서 = 컬럼 순서**: 질문에 적힌 순서대로 컬럼을 낸다. 'X별 A와 B'는 X, A, B 순서.
- **P3 조건과 출력 분리**: 필터·정렬·순위 기준에 쓰인 항목도 질문이 출력하라고 적지 않으면 내지 않는다.
- **P4 엔터티 표기**: 제품→제품명(product_name), 고객사→회사명(company_name), 공급업체→회사명, 배송사→배송사명, 카테고리→카테고리명, 직원→이름(first_name || ' ' || last_name 한 컬럼), 주문→주문번호(order_id). ID는 질문에 'ID'라고 적을 때만 낸다.
- **P5 비율·순위**: 비율은 0~100 퍼센트 값. 근거 건수나 기준값(전월 매출 등)은 질문에 적을 때만 낸다. 순위 번호는 '순위'라고 적을 때만 낸다.
- **P6 질문당 의도 하나**: '몇 개'는 개수 한 값만 낸다. 개수와 목록을 한 질문에서 동시에 묻지 않는다.
- **P7 행 순서**: 정렬이 필요한 질문은 질문에 순서를 적는다(예: '매출이 높은 순서로'). 상위 N 질문은 그 기준의 내림차순.
- **P8 값 표현**: 금액과 비율은 소수 둘째 자리 반올림, 평균 일수는 소수 첫째 자리. 매출 = unit_price * quantity * (1 - discount). 월은 형식을 지정한 문항만 그 형식을 따른다 — 지정 없음: 월 번호 1~12(L2-02), 지정 있음: 힌트에 `YYYY-MM`(L4-05).

## 수정 문항 (21개)

seq는 평가 화면 번호(L1-01 = 0)입니다.

### seq 1 (L1-02)

- **이전 질문**: 단종된 제품 목록을 보여주세요.
- **새 질문**: 단종된 제품의 제품명을 제품명 순서로 보여주세요.
- **출력 항목**: 제품명
- **컬럼**: `product_id, product_name` → `product_name`
- **이유**: 질문에 없는 product_id 제거 (P4)
- **힌트**: products.discontinued = 1 이면 단종.

```sql
SELECT product_name FROM products WHERE discontinued = 1 ORDER BY product_name;
```

### seq 2 (L1-03)

- **이전 질문**: 재고가 재주문 기준 아래로 떨어진 판매 중 제품은?
- **새 질문**: 판매 중인 제품 중 재고 수량이 재주문 기준보다 적은 제품의 제품명, 재고 수량, 재주문 기준을 제품명 순서로 보여주세요.
- **출력 항목**: 제품명 → 재고 수량 → 재주문 기준
- **컬럼**: `product_name, units_in_stock, reorder_level, units_on_order` → `product_name, units_in_stock, reorder_level`
- **이유**: 질문에 없는 units_on_order 제거, 조건 컬럼은 출력 항목으로 명시 (P1, P3)
- **힌트**: 판매 중 = discontinued = 0. 재주문 기준 = reorder_level.

```sql
SELECT product_name, units_in_stock, reorder_level FROM products WHERE discontinued = 0 AND units_in_stock < reorder_level ORDER BY product_name;
```

### seq 3 (L1-04)

- **이전 질문**: 단가가 가장 비싼 제품 10개를 알려주세요.
- **새 질문**: 단가가 가장 비싼 제품 10개의 제품명과 단가를 보여주세요.
- **출력 항목**: 제품명 → 단가
- **컬럼**: `product_name, unit_price` → `product_name, unit_price`
- **이유**: 정렬 기준인 단가를 출력 항목으로 명시 (P3)

```sql
SELECT product_name, unit_price FROM products ORDER BY unit_price DESC, product_name LIMIT 10;
```

### seq 7 (L1-08)

- **이전 질문**: 운송비가 500달러 이상인 주문을 보여주세요.
- **새 질문**: 운송비가 500 이상인 주문의 주문번호, 주문일, 운송비를 운송비가 큰 순서로 보여주세요.
- **출력 항목**: 주문번호 → 주문일 → 운송비
- **컬럼**: `order_id, customer_id, order_date, freight` → `order_id, order_date, freight`
- **이유**: 질문에 없는 customer_id 제거, 출력 항목 명시 (P1, P4)

```sql
SELECT order_id, order_date, freight FROM orders WHERE freight >= 500 ORDER BY freight DESC;
```

### seq 12 (L2-05)

- **이전 질문**: 연도별 매출과 주문 건수 추이를 보여주세요.
- **새 질문**: 연도별 매출과 주문 건수를 연도 순서로 보여주세요.
- **출력 항목**: 연도 → 매출 → 주문 건수
- **컬럼**: `year, order_count, revenue` → `year, revenue, order_count`
- **이유**: 질문 순서(매출 → 주문 건수)와 컬럼 순서 일치 (P2)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT EXTRACT(YEAR FROM o.order_date)::int AS year, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue, COUNT(DISTINCT o.order_id) AS order_count FROM orders o JOIN order_details od ON od.order_id = o.order_id GROUP BY 1 ORDER BY 1;
```

### seq 14 (L2-07)

- **이전 질문**: 주문을 20건 이상 한 고객사는 어디인가요?
- **새 질문**: 주문을 20건 이상 한 고객사의 회사명과 주문 건수를 주문 건수가 많은 순서로 보여주세요.
- **출력 항목**: 회사명 → 주문 건수
- **컬럼**: `company_name, order_count` → `company_name, order_count`
- **이유**: 조건 컬럼(주문 건수)을 출력 항목으로 명시 (P3)

```sql
SELECT c.company_name, COUNT(*) AS order_count FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.company_name HAVING COUNT(*) >= 20 ORDER BY order_count DESC, c.company_name;
```

### seq 15 (L2-08)

- **이전 질문**: 전체 주문 중 요청일보다 늦게 배송된 주문의 비율은?
- **새 질문**: 배송된 주문 중 요청일보다 늦게 배송된 주문의 비율(%)은 얼마인가요?
- **출력 항목**: 지연 비율(%)
- **컬럼**: `late_orders, shipped_orders, late_pct` → `late_pct`
- **이유**: 질문에 없는 근거 건수 2개 제거 (P5)
- **힌트**: 지연 = shipped_date > required_date. 미배송(shipped_date IS NULL) 주문은 제외.

```sql
SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE shipped_date > required_date) / COUNT(*), 2) AS late_pct FROM orders WHERE shipped_date IS NOT NULL;
```

### seq 16 (L3-01)

- **이전 질문**: 1997년 매출 상위 5개 고객사는?
- **새 질문**: 1997년 매출 상위 5개 고객사의 회사명, 국가, 매출을 보여주세요.
- **출력 항목**: 회사명 → 국가 → 매출
- **컬럼**: `company_name, country, revenue` → `company_name, country, revenue`
- **이유**: 질문에 없던 국가·매출을 출력 항목으로 명시 (P1, P3)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT c.company_name, c.country, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.company_name, c.country ORDER BY revenue DESC LIMIT 5;
```

### seq 17 (L3-02)

- **이전 질문**: 1997년 직원별 판매 실적(매출, 주문 건수)을 보여주세요.
- **새 질문**: 1997년 직원별 매출과 주문 건수를 매출이 높은 순서로 보여주세요.
- **출력 항목**: 이름 → 매출 → 주문 건수
- **컬럼**: `employee_name, order_count, revenue` → `employee_name, revenue, order_count`
- **이유**: 질문 순서(매출 → 주문 건수)와 컬럼 순서 일치 (P2)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT e.first_name || ' ' || e.last_name AS employee_name, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue, COUNT(DISTINCT o.order_id) AS order_count FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN employees e ON e.employee_id = o.employee_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY e.employee_id, e.first_name, e.last_name ORDER BY revenue DESC;
```

### seq 19 (L3-04)

- **이전 질문**: 판매 수량 기준으로 가장 많이 팔린 제품 10개는?
- **새 질문**: 판매 수량이 가장 많은 제품 10개의 제품명과 판매 수량을 보여주세요.
- **출력 항목**: 제품명 → 판매 수량
- **컬럼**: `product_name, total_quantity` → `product_name, total_quantity`
- **이유**: 정렬 기준인 판매 수량을 출력 항목으로 명시 (P3)

```sql
SELECT p.product_name, SUM(od.quantity) AS total_quantity FROM order_details od JOIN products p ON p.product_id = od.product_id GROUP BY p.product_name ORDER BY total_quantity DESC, p.product_name LIMIT 10;
```

### seq 21 (L3-06)

- **이전 질문**: 각 직원과 그 직원의 상사 이름을 보여주세요.
- **새 질문**: 각 직원의 이름과 상사 이름을 직원 ID 순서로 보여주세요. 상사가 없는 직원도 포함합니다.
- **출력 항목**: 이름 → 상사 이름
- **컬럼**: `employee_name, title, manager_name` → `employee_name, manager_name`
- **이유**: 질문에 없는 title 제거, 행 순서 명시 (P1, P7)
- **힌트**: employees.reports_to = 상사의 employee_id. 상사가 없는 직원도 포함.

```sql
SELECT e.first_name || ' ' || e.last_name AS employee_name, m.first_name || ' ' || m.last_name AS manager_name FROM employees e LEFT JOIN employees m ON m.employee_id = e.reports_to ORDER BY e.employee_id;
```

### seq 22 (L3-07)

- **이전 질문**: 배송사별로 지연 배송 건수와 지연율을 비교해 주세요.
- **새 질문**: 배송사별 지연 배송 건수와 지연율(%)을 지연율이 높은 순서로 보여주세요. 지연은 요청일보다 늦게 배송된 경우이며 미배송 주문은 제외합니다.
- **출력 항목**: 배송사명 → 지연 건수 → 지연율(%)
- **컬럼**: `shipper, late_orders, shipped_orders, late_pct` → `shipper, late_orders, late_pct`
- **이유**: 질문에 없는 배송 건수 제거 (P5)
- **힌트**: 지연 = shipped_date > required_date. 미배송 주문 제외.

```sql
SELECT s.company_name AS shipper, COUNT(*) FILTER (WHERE o.shipped_date > o.required_date) AS late_orders, ROUND(100.0 * COUNT(*) FILTER (WHERE o.shipped_date > o.required_date) / COUNT(*), 2) AS late_pct FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via WHERE o.shipped_date IS NOT NULL GROUP BY s.company_name ORDER BY late_pct DESC;
```

### seq 24 (L4-01)

- **이전 질문**: 한 번도 주문하지 않은 고객사는?
- **새 질문**: 한 번도 주문하지 않은 고객사의 회사명을 회사명 순서로 보여주세요.
- **출력 항목**: 회사명
- **컬럼**: `customer_id, company_name, country` → `company_name`
- **이유**: 질문에 없는 customer_id, country 제거 (P1, P4)

```sql
SELECT c.company_name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id) ORDER BY c.company_name;
```

### seq 25 (L4-02)

- **이전 질문**: 전체 평균 단가보다 비싼 제품은 몇 개이고 어떤 것들인가요?
- **새 질문**: 전체 평균 단가보다 비싼 제품의 제품명과 단가를 단가가 높은 순서로 보여주세요.
- **출력 항목**: 제품명 → 단가
- **컬럼**: `product_name, unit_price` → `product_name, unit_price`
- **이유**: 개수와 목록을 동시에 묻던 질문을 목록 하나로 정리 (P6)

```sql
SELECT product_name, unit_price FROM products WHERE unit_price > (SELECT AVG(unit_price) FROM products) ORDER BY unit_price DESC;
```

### seq 26 (L4-03)

- **이전 질문**: 카테고리마다 가장 비싼 제품 하나씩 보여주세요.
- **새 질문**: 카테고리마다 단가가 가장 비싼 제품 하나씩, 카테고리명, 제품명, 단가를 카테고리명 순서로 보여주세요.
- **출력 항목**: 카테고리명 → 제품명 → 단가
- **컬럼**: `category_name, product_name, unit_price` → `category_name, product_name, unit_price`
- **이유**: 단가를 출력 항목으로 명시 (P3)

```sql
SELECT DISTINCT ON (c.category_name) c.category_name, p.product_name, p.unit_price FROM products p JOIN categories c ON c.category_id = p.category_id ORDER BY c.category_name, p.unit_price DESC, p.product_name;
```

### seq 27 (L4-04)

- **이전 질문**: 1997년 고객사 매출 순위 상위 10곳과 전체 매출 대비 비중을 보여주세요.
- **새 질문**: 1997년 매출 상위 10개 고객사의 순위, 회사명, 매출, 1997년 전체 매출 대비 비중(%)을 보여주세요.
- **출력 항목**: 순위 → 회사명 → 매출 → 비중(%)
- **컬럼**: `rnk, company_name, revenue, share_pct` → `rnk, company_name, revenue, share_pct`
- **이유**: 순위·매출을 출력 항목으로 명시 (P3, P5)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH cust AS (SELECT c.company_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.company_name) SELECT RANK() OVER (ORDER BY revenue DESC) AS rnk, company_name, ROUND(revenue::numeric, 2) AS revenue, ROUND((100 * revenue / SUM(revenue) OVER ())::numeric, 2) AS share_pct FROM cust ORDER BY rnk LIMIT 10;
```

### seq 28 (L4-05)

- **이전 질문**: 1997년 월별 매출과 전월 대비 증감률을 보여주세요.
- **새 질문**: 1997년 월별로 월, 매출, 전월 대비 매출 증감률(%)을 월 순서로 보여주세요. 1월의 증감률은 비워 둡니다.
- **출력 항목**: 월 → 매출 → 전월 대비 증감률(%)
- **컬럼**: `month, revenue, mom_pct` → `month, revenue, mom_pct`
- **이유**: 출력 항목과 1월 처리 명시. 전월 매출은 묻지 않으므로 내지 않음 (P1, P5). 월 표시 형식(`YYYY-MM`)을 힌트로 지정 — 형식이 없으면 월 번호·날짜 어느 쪽도 맞는 답이었다(10-28, P8)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date. 월은 YYYY-MM 형식(예: 1997-01)으로 표시한다.

```sql
WITH m AS (SELECT TO_CHAR(o.order_date, 'YYYY-MM') AS month, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY 1) SELECT month, ROUND(revenue::numeric, 2) AS revenue, ROUND((100 * (revenue - LAG(revenue) OVER (ORDER BY month)) / LAG(revenue) OVER (ORDER BY month))::numeric, 2) AS mom_pct FROM m ORDER BY month;
```

### seq 29 (L4-06)

- **이전 질문**: 국가별로 매출 1위 고객사를 알려주세요.
- **새 질문**: 국가별로 매출 1위 고객사의 국가, 회사명, 매출을 매출이 높은 순서로 보여주세요.
- **출력 항목**: 국가 → 회사명 → 매출
- **컬럼**: `country, company_name, revenue` → `country, company_name, revenue`
- **이유**: 순위 기준인 매출을 출력 항목으로 명시 (P3)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH r AS (SELECT c.country, c.company_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue, ROW_NUMBER() OVER (PARTITION BY c.country ORDER BY SUM(od.unit_price * od.quantity * (1 - od.discount)) DESC) AS rn FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.country, c.company_name) SELECT country, company_name, ROUND(revenue::numeric, 2) AS revenue FROM r WHERE rn = 1 ORDER BY revenue DESC;
```

### seq 31 (L4-08)

- **이전 질문**: 주문을 5건 이상 한 고객 중 평균 주문 간격이 가장 짧은 10곳은?
- **새 질문**: 주문을 5건 이상 한 고객사 중 평균 주문 간격(일)이 가장 짧은 10곳의 회사명과 평균 주문 간격을 보여주세요. 평균 주문 간격은 (마지막 주문일 - 첫 주문일) / (주문 건수 - 1)입니다.
- **출력 항목**: 회사명 → 평균 주문 간격(일)
- **컬럼**: `company_name, order_count, first_order, last_order, avg_days_between` → `company_name, avg_days_between`
- **이유**: 질문에 없는 주문 건수·첫/마지막 주문일 제거 (P1, P3)
- **힌트**: 평균 주문 간격 = (마지막 주문일 - 첫 주문일) / (주문 건수 - 1).

```sql
SELECT c.company_name, ROUND((MAX(o.order_date) - MIN(o.order_date))::numeric / (COUNT(*) - 1), 1) AS avg_days_between FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.company_name HAVING COUNT(*) >= 5 ORDER BY avg_days_between, c.company_name LIMIT 10;
```

### seq 32 (L4-09)

- **이전 질문**: 같은 주문에서 함께 가장 많이 팔린 제품 조합 Top 10은?
- **새 질문**: 같은 주문에 함께 가장 많이 포함된 제품 쌍 10개의 두 제품명과 함께 주문된 횟수를 보여주세요.
- **출력 항목**: 제품명 A → 제품명 B → 함께 주문된 횟수
- **컬럼**: `product_a, product_b, together_count` → `product_a, product_b, together_count`
- **이유**: 정렬 기준인 횟수를 출력 항목으로 명시 (P3)

```sql
SELECT p1.product_name AS product_a, p2.product_name AS product_b, COUNT(*) AS together_count FROM order_details a JOIN order_details b ON b.order_id = a.order_id AND b.product_id > a.product_id JOIN products p1 ON p1.product_id = a.product_id JOIN products p2 ON p2.product_id = b.product_id GROUP BY p1.product_name, p2.product_name ORDER BY together_count DESC, product_a, product_b LIMIT 10;
```

### seq 33 (L4-10)

- **이전 질문**: 전체 매출의 80%를 차지하는 핵심 제품(ABC 분석 A등급)은 몇 개인가요?
- **새 질문**: 전체 매출의 80%를 차지하는 A등급 제품은 몇 개인가요? 매출 내림차순 누적 비중이 80%에 처음 도달하는 제품까지 A등급입니다.
- **출력 항목**: A등급 제품 수
- **컬럼**: `class_a_products, total_products` → `class_a_products`
- **이유**: 질문에 없는 전체 제품 수 제거, A등급 정의를 질문에 포함 (P6)
- **힌트**: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date. 매출 내림차순 누적 비중이 80% 이하인 제품 + 80%를 처음 넘기는 제품까지 A등급.

```sql
WITH pr AS (SELECT od.product_id, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM order_details od GROUP BY od.product_id), cum AS (SELECT (SUM(revenue) OVER (ORDER BY revenue DESC, product_id) - revenue) / SUM(revenue) OVER () AS prev_share FROM pr) SELECT COUNT(*) AS class_a_products FROM cum WHERE prev_share < 0.8;
```

## 원칙에 이미 맞아 유지한 문항 (13개)

| seq | ID | 질문 | 출력 항목 |
|---|---|---|---|
| 0 | L1-01 | 독일에 있는 고객사는 몇 곳인가요? | 고객사 수 |
| 4 | L1-05 | 국가별 고객 수를 많은 순으로 보여주세요. | 국가 → 고객 수 |
| 5 | L1-06 | 1997년에 접수된 주문은 몇 건인가요? | 주문 건수 |
| 6 | L1-07 | 직원들의 이름, 직책, 입사일을 입사 순서대로 보여주세요. | 이름 → 직책 → 입사일 |
| 8 | L2-01 | 카테고리별 제품 수와 평균 단가를 알려주세요. | 카테고리명 → 제품 수 → 평균 단가 |
| 9 | L2-02 | 1997년 월별 주문 건수를 보여주세요. | 월 → 주문 건수 |
| 10 | L2-03 | 배송사별 주문 건수와 평균 운송비는? | 배송사명 → 주문 건수 → 평균 운송비 |
| 11 | L2-04 | 1997년 총 매출은 얼마인가요? | 매출 |
| 13 | L2-06 | 공급업체 국가별로 공급하는 제품 수는? | 국가 → 제품 수 |
| 18 | L3-03 | 카테고리별 전체 매출을 높은 순으로 보여주세요. | 카테고리명 → 매출 |
| 20 | L3-05 | 해산물(Seafood) 제품을 공급하는 업체와 국가를 알려주세요. | 회사명 → 국가 |
| 23 | L3-08 | 직원별 담당 지역(Region)과 담당 테리토리 수를 보여주세요. | 이름 → 담당 지역 → 테리토리 수 |
| 30 | L4-07 | 주문당 평균 품목 수와 평균 주문 금액은? | 주문당 평균 품목 수 → 평균 주문 금액 |

# Northwind Text-to-SQL 골든 세트 (PostgreSQL)
pgxnl + MCP + watsonx Orchestrate 데모용. 모든 SQL은 PostgreSQL 16에서 실행 검증했습니다.
- **DB**: Northwind (pthom/northwind_psql), 14 테이블
- **데이터 기간**: 1996-07-04 ~ 1998-05-06 (주문 830건, 고객 91, 제품 77, 직원 9)
- **매출 정의**: `SUM(od.unit_price * od.quantity * (1 - od.discount))` — unit_price/discount가 `real` 타입이라 `::numeric` 캐스팅 후 ROUND
- **구성**: 단일 질문 34개 (L1~L4) + 멀티턴 시나리오 3개 + 견고성 테스트 6개

## 데이터 주의사항 (스키마 설명에 넣으세요)
- 날짜가 1996~1998년이라 '작년', '최근 3개월' 같은 상대 날짜는 기준 시점을 정해야 합니다.
- `customer_demographics`, `customer_customer_demo`는 비어 있습니다 (0건).
- `products.discontinued`는 integer(0/1)입니다.
- `orders.ship_via` → `shippers.shipper_id`, `employees.reports_to` → `employees.employee_id` (FK 이름이 직관적이지 않음).
- 미배송 주문 21건은 `shipped_date IS NULL`.
- 값이 영어라서 한글 질문의 엔티티(독일→Germany, 음료→Beverages) 매핑이 필요합니다.

## L1. 단일 테이블

### L1-01 독일에 있는 고객사는 몇 곳인가요?
_How many customers are located in Germany?_  ·  `filter, count`

```sql
SELECT COUNT(*) AS customer_count FROM customers WHERE country = 'Germany';
```

| customer_count |
|---|
| 11 |

### L1-02 단종된 제품 목록을 보여주세요.
_List the discontinued products._  ·  `filter, boolean-flag`

> 힌트: products.discontinued = 1 이면 단종.

```sql
SELECT product_id, product_name FROM products WHERE discontinued = 1 ORDER BY product_name;
```

| product_id | product_name |
|---|---|
| 17 | Alice Mutton |
| 1 | Chai |
| 2 | Chang |
| 5 | Chef Anton's Gumbo Mix |
| 24 | Guaraná Fantástica |

_… 외 5행 (총 10행)_

### L1-03 재고가 재주문 기준 아래로 떨어진 판매 중 제품은?
_Which active products have stock below their reorder level?_  ·  `filter, column-compare`

> 힌트: 판매 중 = discontinued = 0. 재주문 기준 = reorder_level.

```sql
SELECT product_name, units_in_stock, reorder_level, units_on_order FROM products WHERE discontinued = 0 AND units_in_stock < reorder_level ORDER BY product_name;
```

| product_name | units_in_stock | reorder_level | units_on_order |
|---|---|---|---|
| Aniseed Syrup | 13 | 25 | 70 |
| Chocolade | 15 | 25 | 70 |
| Gnocchi di nonna Alice | 21 | 30 | 10 |
| Gorgonzola Telino | 0 | 20 | 70 |
| Gravad lax | 11 | 25 | 50 |

_… 외 12행 (총 17행)_

### L1-04 단가가 가장 비싼 제품 10개를 알려주세요.
_Show the 10 most expensive products._  ·  `order, limit`

```sql
SELECT product_name, unit_price FROM products ORDER BY unit_price DESC, product_name LIMIT 10;
```

| product_name | unit_price |
|---|---|
| Côte de Blaye | 263.5 |
| Thüringer Rostbratwurst | 123.79 |
| Mishi Kobe Niku | 97.0 |
| Sir Rodney's Marmalade | 81.0 |
| Carnarvon Tigers | 62.5 |

_… 외 5행 (총 10행)_

### L1-05 국가별 고객 수를 많은 순으로 보여주세요.
_Number of customers per country, most first._  ·  `group, count`

```sql
SELECT country, COUNT(*) AS customer_count FROM customers GROUP BY country ORDER BY customer_count DESC, country;
```

| country | customer_count |
|---|---|
| USA | 13 |
| France | 11 |
| Germany | 11 |
| Brazil | 9 |
| UK | 7 |

_… 외 16행 (총 21행)_

### L1-06 1997년에 접수된 주문은 몇 건인가요?
_How many orders were placed in 1997?_  ·  `date-filter, count`

```sql
SELECT COUNT(*) AS order_count FROM orders WHERE order_date >= DATE '1997-01-01' AND order_date < DATE '1998-01-01';
```

| order_count |
|---|
| 408 |

### L1-07 직원들의 이름, 직책, 입사일을 입사 순서대로 보여주세요.
_List employees with title and hire date, earliest hire first._  ·  `projection, order`

```sql
SELECT first_name || ' ' || last_name AS employee_name, title, hire_date FROM employees ORDER BY hire_date, employee_id;
```

| employee_name | title | hire_date |
|---|---|---|
| Janet Leverling | Sales Representative | 1992-04-01 |
| Nancy Davolio | Sales Representative | 1992-05-01 |
| Andrew Fuller | Vice President, Sales | 1992-08-14 |
| Margaret Peacock | Sales Representative | 1993-05-03 |
| Steven Buchanan | Sales Manager | 1993-10-17 |

_… 외 4행 (총 9행)_

### L1-08 운송비가 500달러 이상인 주문을 보여주세요.
_Show orders with freight of 500 or more._  ·  `filter, numeric`

```sql
SELECT order_id, customer_id, order_date, freight FROM orders WHERE freight >= 500 ORDER BY freight DESC;
```

| order_id | customer_id | order_date | freight |
|---|---|---|---|
| 10540 | QUICK | 1997-05-19 | 1007.64 |
| 10372 | QUEEN | 1996-12-04 | 890.78 |
| 11030 | SAVEA | 1998-04-17 | 830.75 |
| 10691 | QUICK | 1997-10-03 | 810.05 |
| 10514 | ERNSH | 1997-04-22 | 789.95 |

_… 외 8행 (총 13행)_

## L2. 집계

### L2-01 카테고리별 제품 수와 평균 단가를 알려주세요.
_Product count and average unit price per category._  ·  `join, group, avg`

```sql
SELECT c.category_name, COUNT(*) AS product_count, ROUND(AVG(p.unit_price)::numeric, 2) AS avg_unit_price FROM products p JOIN categories c ON c.category_id = p.category_id GROUP BY c.category_name ORDER BY c.category_name;
```

| category_name | product_count | avg_unit_price |
|---|---|---|
| Beverages | 12 | 37.98 |
| Condiments | 12 | 22.85 |
| Confections | 13 | 25.16 |
| Dairy Products | 10 | 28.73 |
| Grains/Cereals | 7 | 20.25 |

_… 외 3행 (총 8행)_

### L2-02 1997년 월별 주문 건수를 보여주세요.
_Monthly order count in 1997._  ·  `date-trunc, group`

```sql
SELECT EXTRACT(MONTH FROM order_date)::int AS month, COUNT(*) AS order_count FROM orders WHERE order_date >= DATE '1997-01-01' AND order_date < DATE '1998-01-01' GROUP BY 1 ORDER BY 1;
```

| month | order_count |
|---|---|
| 1 | 33 |
| 2 | 29 |
| 3 | 30 |
| 4 | 31 |
| 5 | 32 |

_… 외 7행 (총 12행)_

### L2-03 배송사별 주문 건수와 평균 운송비는?
_Order count and average freight by shipper._  ·  `join, group, avg`

> 힌트: orders.ship_via = shippers.shipper_id.

```sql
SELECT s.company_name AS shipper, COUNT(*) AS order_count, ROUND(AVG(o.freight)::numeric, 2) AS avg_freight FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via GROUP BY s.company_name ORDER BY s.company_name;
```

| shipper | order_count | avg_freight |
|---|---|---|
| Federal Shipping | 255 | 80.44 |
| Speedy Express | 249 | 65.0 |
| United Package | 326 | 86.64 |

### L2-04 1997년 총 매출은 얼마인가요?
_What was total revenue in 1997?_  ·  `aggregate, revenue`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01';
```

| revenue |
|---|
| 617085.2 |

### L2-05 연도별 매출과 주문 건수 추이를 보여주세요.
_Revenue and order count by year._  ·  `group, revenue, trend`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT EXTRACT(YEAR FROM o.order_date)::int AS year, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id GROUP BY 1 ORDER BY 1;
```

| year | order_count | revenue |
|---|---|---|
| 1996 | 152 | 208083.97 |
| 1997 | 408 | 617085.2 |
| 1998 | 270 | 440623.87 |

### L2-06 공급업체 국가별로 공급하는 제품 수는?
_Number of products supplied per supplier country._  ·  `join, group`

```sql
SELECT s.country, COUNT(*) AS product_count FROM products p JOIN suppliers s ON s.supplier_id = p.supplier_id GROUP BY s.country ORDER BY product_count DESC, s.country;
```

| country | product_count |
|---|---|
| USA | 12 |
| Germany | 9 |
| Australia | 8 |
| UK | 7 |
| Japan | 6 |

_… 외 11행 (총 16행)_

### L2-07 주문을 20건 이상 한 고객사는 어디인가요?
_Which customers placed 20 or more orders?_  ·  `having`

```sql
SELECT c.company_name, COUNT(*) AS order_count FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.company_name HAVING COUNT(*) >= 20 ORDER BY order_count DESC, c.company_name;
```

| company_name | order_count |
|---|---|
| Save-a-lot Markets | 31 |
| Ernst Handel | 30 |
| QUICK-Stop | 28 |

### L2-08 전체 주문 중 요청일보다 늦게 배송된 주문의 비율은?
_What share of shipped orders shipped after the required date?_  ·  `case, ratio`

> 힌트: 지연 = shipped_date > required_date. 미배송(shipped_date IS NULL) 주문은 제외.

```sql
SELECT COUNT(*) FILTER (WHERE shipped_date > required_date) AS late_orders, COUNT(*) AS shipped_orders, ROUND(100.0 * COUNT(*) FILTER (WHERE shipped_date > required_date) / COUNT(*), 2) AS late_pct FROM orders WHERE shipped_date IS NOT NULL;
```

| late_orders | shipped_orders | late_pct |
|---|---|---|
| 37 | 809 | 4.57 |

## L3. 다중 조인

### L3-01 1997년 매출 상위 5개 고객사는?
_Top 5 customers by revenue in 1997._  ·  `join, revenue, topn`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT c.company_name, c.country, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.company_name, c.country ORDER BY revenue DESC LIMIT 5;
```

| company_name | country | revenue |
|---|---|---|
| QUICK-Stop | Germany | 61109.91 |
| Save-a-lot Markets | USA | 57713.57 |
| Ernst Handel | Austria | 48096.26 |
| Mère Paillarde | Canada | 23332.31 |
| Hungry Owl All-Night Grocers | Ireland | 20454.4 |

### L3-02 1997년 직원별 판매 실적(매출, 주문 건수)을 보여주세요.
_Sales by employee in 1997 (revenue and order count)._  ·  `join, revenue`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT e.first_name || ' ' || e.last_name AS employee_name, COUNT(DISTINCT o.order_id) AS order_count, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN employees e ON e.employee_id = o.employee_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY e.employee_id, e.first_name, e.last_name ORDER BY revenue DESC;
```

| employee_name | order_count | revenue |
|---|---|---|
| Margaret Peacock | 81 | 128809.79 |
| Janet Leverling | 71 | 108026.16 |
| Nancy Davolio | 55 | 93148.08 |
| Andrew Fuller | 41 | 70444.14 |
| Robert King | 36 | 60471.19 |

_… 외 4행 (총 9행)_

### L3-03 카테고리별 전체 매출을 높은 순으로 보여주세요.
_Total revenue by category, highest first._  ·  `join, revenue`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
SELECT c.category_name, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM order_details od JOIN products p ON p.product_id = od.product_id JOIN categories c ON c.category_id = p.category_id GROUP BY c.category_name ORDER BY revenue DESC;
```

| category_name | revenue |
|---|---|
| Beverages | 267868.18 |
| Dairy Products | 234507.28 |
| Confections | 167357.23 |
| Meat/Poultry | 163022.36 |
| Seafood | 131261.74 |

_… 외 3행 (총 8행)_

### L3-04 판매 수량 기준으로 가장 많이 팔린 제품 10개는?
_Top 10 products by quantity sold._  ·  `join, topn`

```sql
SELECT p.product_name, SUM(od.quantity) AS total_quantity FROM order_details od JOIN products p ON p.product_id = od.product_id GROUP BY p.product_name ORDER BY total_quantity DESC, p.product_name LIMIT 10;
```

| product_name | total_quantity |
|---|---|
| Camembert Pierrot | 1577 |
| Raclette Courdavault | 1496 |
| Gorgonzola Telino | 1397 |
| Gnocchi di nonna Alice | 1263 |
| Pavlova | 1158 |

_… 외 5행 (총 10행)_

### L3-05 해산물(Seafood) 제품을 공급하는 업체와 국가를 알려주세요.
_Which suppliers (and countries) supply Seafood products?_  ·  `join, filter-by-name`

```sql
SELECT DISTINCT s.company_name, s.country FROM products p JOIN suppliers s ON s.supplier_id = p.supplier_id JOIN categories c ON c.category_id = p.category_id WHERE c.category_name = 'Seafood' ORDER BY s.company_name;
```

| company_name | country |
|---|---|
| Escargots Nouveaux | France |
| Lyngbysild | Denmark |
| Mayumi's | Japan |
| New England Seafood Cannery | USA |
| Nord-Ost-Fisch Handelsgesellschaft mbH | Germany |

_… 외 3행 (총 8행)_

### L3-06 각 직원과 그 직원의 상사 이름을 보여주세요.
_Show each employee with their manager's name._  ·  `self-join, left-join`

> 힌트: employees.reports_to = 상사의 employee_id. 상사가 없는 직원도 포함.

```sql
SELECT e.first_name || ' ' || e.last_name AS employee_name, e.title, m.first_name || ' ' || m.last_name AS manager_name FROM employees e LEFT JOIN employees m ON m.employee_id = e.reports_to ORDER BY e.employee_id;
```

| employee_name | title | manager_name |
|---|---|---|
| Nancy Davolio | Sales Representative | Andrew Fuller |
| Andrew Fuller | Vice President, Sales |  |
| Janet Leverling | Sales Representative | Andrew Fuller |
| Margaret Peacock | Sales Representative | Andrew Fuller |
| Steven Buchanan | Sales Manager | Andrew Fuller |

_… 외 4행 (총 9행)_

### L3-07 배송사별로 지연 배송 건수와 지연율을 비교해 주세요.
_Compare late shipments and late rate by shipper._  ·  `join, conditional-agg`

> 힌트: 지연 = shipped_date > required_date. 미배송 주문 제외.

```sql
SELECT s.company_name AS shipper, COUNT(*) FILTER (WHERE o.shipped_date > o.required_date) AS late_orders, COUNT(*) AS shipped_orders, ROUND(100.0 * COUNT(*) FILTER (WHERE o.shipped_date > o.required_date) / COUNT(*), 2) AS late_pct FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via WHERE o.shipped_date IS NOT NULL GROUP BY s.company_name ORDER BY late_pct DESC;
```

| shipper | late_orders | shipped_orders | late_pct |
|---|---|---|---|
| United Package | 16 | 315 | 5.08 |
| Speedy Express | 12 | 245 | 4.9 |
| Federal Shipping | 9 | 249 | 3.61 |

### L3-08 직원별 담당 지역(Region)과 담당 테리토리 수를 보여주세요.
_Each employee's region(s) and number of territories._  ·  `4-way-join, string-agg`

> 힌트: employees → employee_territories → territories → region. 일부 Northwind 배포본은 region_description에 공백 패딩이 있어 TRIM 권장.

```sql
SELECT e.first_name || ' ' || e.last_name AS employee_name, STRING_AGG(DISTINCT TRIM(r.region_description), ', ') AS regions, COUNT(*) AS territory_count FROM employees e JOIN employee_territories et ON et.employee_id = e.employee_id JOIN territories t ON t.territory_id = et.territory_id JOIN region r ON r.region_id = t.region_id GROUP BY e.employee_id, e.first_name, e.last_name ORDER BY e.employee_id;
```

| employee_name | regions | territory_count |
|---|---|---|
| Nancy Davolio | Eastern | 2 |
| Andrew Fuller | Eastern | 7 |
| Janet Leverling | Southern | 4 |
| Margaret Peacock | Eastern | 3 |
| Steven Buchanan | Eastern | 7 |

_… 외 4행 (총 9행)_

## L4. 서브쿼리·윈도우·PG 고유 문법

### L4-01 한 번도 주문하지 않은 고객사는?
_Which customers have never placed an order?_  ·  `not-exists, anti-join`

```sql
SELECT c.customer_id, c.company_name, c.country FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id) ORDER BY c.company_name;
```

| customer_id | company_name | country |
|---|---|---|
| FISSA | FISSA Fabrica Inter. Salchichas S.A. | Spain |
| PARIS | Paris spécialités | France |

### L4-02 전체 평균 단가보다 비싼 제품은 몇 개이고 어떤 것들인가요?
_Products priced above the overall average unit price._  ·  `scalar-subquery`

```sql
SELECT product_name, unit_price FROM products WHERE unit_price > (SELECT AVG(unit_price) FROM products) ORDER BY unit_price DESC;
```

| product_name | unit_price |
|---|---|
| Côte de Blaye | 263.5 |
| Thüringer Rostbratwurst | 123.79 |
| Mishi Kobe Niku | 97.0 |
| Sir Rodney's Marmalade | 81.0 |
| Carnarvon Tigers | 62.5 |

_… 외 20행 (총 25행)_

### L4-03 카테고리마다 가장 비싼 제품 하나씩 보여주세요.
_The most expensive product in each category._  ·  `distinct-on, pg-specific`

```sql
SELECT DISTINCT ON (c.category_name) c.category_name, p.product_name, p.unit_price FROM products p JOIN categories c ON c.category_id = p.category_id ORDER BY c.category_name, p.unit_price DESC, p.product_name;
```

| category_name | product_name | unit_price |
|---|---|---|
| Beverages | Côte de Blaye | 263.5 |
| Condiments | Vegie-spread | 43.9 |
| Confections | Sir Rodney's Marmalade | 81.0 |
| Dairy Products | Raclette Courdavault | 55.0 |
| Grains/Cereals | Gnocchi di nonna Alice | 38.0 |

_… 외 3행 (총 8행)_

### L4-04 1997년 고객사 매출 순위 상위 10곳과 전체 매출 대비 비중을 보여주세요.
_Top 10 customers by 1997 revenue with rank and share of total._  ·  `window, rank, share`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH cust AS (SELECT c.company_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.company_name) SELECT RANK() OVER (ORDER BY revenue DESC) AS rnk, company_name, ROUND(revenue::numeric, 2) AS revenue, ROUND((100 * revenue / SUM(revenue) OVER ())::numeric, 2) AS share_pct FROM cust ORDER BY rnk LIMIT 10;
```

| rnk | company_name | revenue | share_pct |
|---|---|---|---|
| 1 | QUICK-Stop | 61109.91 | 9.9 |
| 2 | Save-a-lot Markets | 57713.57 | 9.35 |
| 3 | Ernst Handel | 48096.26 | 7.79 |
| 4 | Mère Paillarde | 23332.31 | 3.78 |
| 5 | Hungry Owl All-Night Grocers | 20454.4 | 3.31 |

_… 외 5행 (총 10행)_

### L4-05 1997년 월별 매출과 전월 대비 증감률을 보여주세요.
_1997 monthly revenue with month-over-month growth._  ·  `window, lag, growth`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH m AS (SELECT DATE_TRUNC('month', o.order_date)::date AS month, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY 1) SELECT month, ROUND(revenue::numeric, 2) AS revenue, ROUND((100 * (revenue - LAG(revenue) OVER (ORDER BY month)) / LAG(revenue) OVER (ORDER BY month))::numeric, 2) AS mom_pct FROM m ORDER BY month;
```

| month | revenue | mom_pct |
|---|---|---|
| 1997-01-01 | 61258.07 |  |
| 1997-02-01 | 38483.63 | -37.18 |
| 1997-03-01 | 38547.22 | 0.17 |
| 1997-04-01 | 53032.95 | 37.58 |
| 1997-05-01 | 53781.29 | 1.41 |

_… 외 7행 (총 12행)_

### L4-06 국가별로 매출 1위 고객사를 알려주세요.
_Top customer by revenue in each country._  ·  `window, partition, top1-per-group`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH r AS (SELECT c.country, c.company_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue, ROW_NUMBER() OVER (PARTITION BY c.country ORDER BY SUM(od.unit_price * od.quantity * (1 - od.discount)) DESC) AS rn FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.country, c.company_name) SELECT country, company_name, ROUND(revenue::numeric, 2) AS revenue FROM r WHERE rn = 1 ORDER BY revenue DESC;
```

| country | company_name | revenue |
|---|---|---|
| Germany | QUICK-Stop | 110277.31 |
| Austria | Ernst Handel | 104874.98 |
| USA | Save-a-lot Markets | 104361.95 |
| Ireland | Hungry Owl All-Night Grocers | 49979.91 |
| Brazil | Hanari Carnes | 32841.37 |

_… 외 16행 (총 21행)_

### L4-07 주문당 평균 품목 수와 평균 주문 금액은?
_Average line items per order and average order value._  ·  `two-level-agg, cte`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date.

```sql
WITH per_order AS (SELECT od.order_id, COUNT(*) AS line_items, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS order_value FROM order_details od GROUP BY od.order_id) SELECT ROUND(AVG(line_items), 2) AS avg_line_items, ROUND(AVG(order_value)::numeric, 2) AS avg_order_value FROM per_order;
```

| avg_line_items | avg_order_value |
|---|---|
| 2.6 | 1525.05 |

### L4-08 주문을 5건 이상 한 고객 중 평균 주문 간격이 가장 짧은 10곳은?
_Among customers with 5+ orders, the 10 with the shortest average days between orders._  ·  `date-diff, having`

> 힌트: 평균 주문 간격 = (마지막 주문일 - 첫 주문일) / (주문 건수 - 1).

```sql
SELECT c.company_name, COUNT(*) AS order_count, MIN(o.order_date) AS first_order, MAX(o.order_date) AS last_order, ROUND((MAX(o.order_date) - MIN(o.order_date))::numeric / (COUNT(*) - 1), 1) AS avg_days_between FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.company_name HAVING COUNT(*) >= 5 ORDER BY avg_days_between, c.company_name LIMIT 10;
```

| company_name | order_count | first_order | last_order | avg_days_between |
|---|---|---|---|---|
| Save-a-lot Markets | 31 | 1996-10-08 | 1998-05-01 | 19.0 |
| Ernst Handel | 30 | 1996-07-17 | 1998-05-05 | 22.7 |
| QUICK-Stop | 28 | 1996-08-05 | 1998-04-14 | 22.9 |
| Mère Paillarde | 13 | 1996-10-17 | 1997-10-30 | 31.5 |
| Hungry Owl All-Night Grocers | 19 | 1996-09-05 | 1998-04-30 | 33.4 |

_… 외 5행 (총 10행)_

### L4-09 같은 주문에서 함께 가장 많이 팔린 제품 조합 Top 10은?
_Top 10 product pairs most often bought in the same order._  ·  `self-join, market-basket`

```sql
SELECT p1.product_name AS product_a, p2.product_name AS product_b, COUNT(*) AS together_count FROM order_details a JOIN order_details b ON b.order_id = a.order_id AND b.product_id > a.product_id JOIN products p1 ON p1.product_id = a.product_id JOIN products p2 ON p2.product_id = b.product_id GROUP BY p1.product_name, p2.product_name ORDER BY together_count DESC, product_a, product_b LIMIT 10;
```

| product_a | product_b | together_count |
|---|---|---|
| Sir Rodney's Scones | Sirop d'érable | 8 |
| Pavlova | Gorgonzola Telino | 7 |
| Camembert Pierrot | Flotemysost | 6 |
| Gorgonzola Telino | Mozzarella di Giovanni | 6 |
| Nord-Ost Matjeshering | Tourtière | 6 |

_… 외 5행 (총 10행)_

### L4-10 전체 매출의 80%를 차지하는 핵심 제품(ABC 분석 A등급)은 몇 개인가요?
_How many products make up the top 80% of revenue (ABC class A)?_  ·  `window, running-total, abc`

> 힌트: 매출 = order_details.unit_price * quantity * (1 - discount). 주문 기준일은 orders.order_date. 매출 내림차순 누적 비중이 80% 이하인 제품 + 80%를 처음 넘기는 제품까지 A등급.

```sql
WITH pr AS (SELECT od.product_id, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM order_details od GROUP BY od.product_id), cum AS (SELECT product_id, revenue, SUM(revenue) OVER (ORDER BY revenue DESC, product_id) / SUM(revenue) OVER () AS cum_share, (SUM(revenue) OVER (ORDER BY revenue DESC, product_id) - revenue) / SUM(revenue) OVER () AS prev_share FROM pr) SELECT COUNT(*) AS class_a_products, (SELECT COUNT(*) FROM pr) AS total_products FROM cum WHERE prev_share < 0.8;
```

| class_a_products | total_products |
|---|---|
| 36 | 77 |

## L5. 멀티턴 시나리오
이전 턴의 맥락(기간, 선택된 엔티티)을 이어받아야 정답이 나옵니다.

### C1. 카테고리 → 제품 → 고객 드릴다운

**턴 1.** 1997년 카테고리별 매출을 보여줘.  
_Show 1997 revenue by category._

```sql
SELECT c.category_name, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN products p ON p.product_id = od.product_id JOIN categories c ON c.category_id = p.category_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.category_name ORDER BY revenue DESC;
```

| category_name | revenue |
|---|---|
| Dairy Products | 115387.64 |
| Beverages | 103924.31 |
| Confections | 82657.75 |

_… 외 5행 (총 8행)_

**턴 2.** 그중 음료(Beverages)만 제품별로 나눠줘.  
_Break Beverages down by product._

```sql
SELECT p.product_name, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN products p ON p.product_id = od.product_id JOIN categories c ON c.category_id = p.category_id WHERE c.category_name = 'Beverages' AND o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY p.product_name ORDER BY revenue DESC;
```

| product_name | revenue |
|---|---|
| Côte de Blaye | 49198.09 |
| Ipoh Coffee | 11069.9 |
| Lakkalikööri | 7379.1 |

_… 외 9행 (총 12행)_

**턴 3.** 1위 제품을 가장 많이 산 고객 3곳은?  
_Which 3 customers bought the most of the top product?_

> 이전 턴 결과의 1위 제품(Côte de Blaye)을 기억해야 함. 기간 조건(1997) 유지.

```sql
SELECT c.company_name, SUM(od.quantity) AS quantity, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN products p ON p.product_id = od.product_id JOIN customers c ON c.customer_id = o.customer_id WHERE p.product_name = 'Côte de Blaye' AND o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY c.company_name ORDER BY revenue DESC LIMIT 3;
```

| company_name | quantity | revenue |
|---|---|---|
| Simons bistro | 50 | 10540.0 |
| Mère Paillarde | 49 | 8263.36 |
| QUICK-Stop | 30 | 7905.0 |

### C2. 배송 지연 원인 추적

**턴 1.** 지연 배송이 가장 많은 배송사는 어디야?  
_Which shipper has the most late shipments?_

```sql
SELECT s.company_name AS shipper, COUNT(*) AS late_orders FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via WHERE o.shipped_date > o.required_date GROUP BY s.company_name ORDER BY late_orders DESC LIMIT 1;
```

| shipper | late_orders |
|---|---|
| United Package | 16 |

**턴 2.** 그 배송사의 지연 주문을 도착 국가별로 보여줘.  
_Show that shipper's late orders by destination country._

> 이전 턴의 배송사(United Package)를 이어받아야 함.

```sql
SELECT o.ship_country, COUNT(*) AS late_orders, ROUND(AVG(o.shipped_date - o.required_date), 1) AS avg_days_late FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via WHERE s.company_name = 'United Package' AND o.shipped_date > o.required_date GROUP BY o.ship_country ORDER BY late_orders DESC, o.ship_country;
```

| ship_country | late_orders | avg_days_late |
|---|---|---|
| USA | 4 | 3.3 |
| France | 2 | 10.0 |
| Germany | 2 | 4.0 |

_… 외 7행 (총 10행)_

### C3. 직원 실적 비교

**턴 1.** Margaret Peacock의 1997년 매출은?  
_Margaret Peacock's revenue in 1997?_

```sql
SELECT ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN employees e ON e.employee_id = o.employee_id WHERE e.first_name = 'Margaret' AND e.last_name = 'Peacock' AND o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01';
```

| revenue |
|---|
| 128809.79 |

**턴 2.** 다른 직원들과 비교하면 몇 등이야?  
_How does she rank against the other employees?_

```sql
WITH s AS (SELECT e.first_name || ' ' || e.last_name AS employee_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o JOIN order_details od ON od.order_id = o.order_id JOIN employees e ON e.employee_id = o.employee_id WHERE o.order_date >= DATE '1997-01-01' AND o.order_date < DATE '1998-01-01' GROUP BY e.employee_id, e.first_name, e.last_name) SELECT RANK() OVER (ORDER BY revenue DESC) AS rnk, employee_name, ROUND(revenue::numeric, 2) AS revenue FROM s ORDER BY rnk;
```

| rnk | employee_name | revenue |
|---|---|---|
| 1 | Margaret Peacock | 128809.79 |
| 2 | Janet Leverling | 108026.16 |
| 3 | Nancy Davolio | 93148.08 |

_… 외 6행 (총 9행)_

## 에이전트 견고성 테스트
정답 SQL보다 **에이전트의 대응 방식**을 확인하는 질문입니다.

| ID | 유형 | 질문 | 기대 동작 |
|---|---|---|---|
| E-01 | relative-date | 작년 매출 알려줘. | 데이터 기간이 1996-07 ~ 1998-05임을 알리고 기준 연도를 되묻거나, 데이터상 마지막 완결 연도(1997)로 가정했음을 명시. |
| E-02 | unanswerable | 고객 만족도 점수 평균은? | 해당 정보가 스키마에 없다고 답변. 임의의 컬럼으로 SQL 생성 금지. |
| E-03 | empty-table | 고객 유형(demographics)별 고객 수는? | customer_demographics / customer_customer_demo 테이블이 비어 있음(0건)을 설명. |
| E-04 | write-intent | Chai 가격을 10% 올려줘. | 조회 전용 에이전트이므로 UPDATE 거부. pgxnl validate 단계에서 DML 차단. |
| E-05 | ambiguous | 제일 잘 나가는 제품은? | 기준(매출 vs 수량)을 되묻거나, 가정한 기준을 명시하고 답변(매출 1위 Côte de Blaye / 수량 1위 Camembert Pierrot). |
| E-06 | korean-entity | 독일 고객 중 베를린에 있는 곳은? | 한글 지명(독일, 베를린)을 데이터 값('Germany', 'Berlin')으로 매핑. 정답: Alfreds Futterkiste. |

## 추천 데모 순서 (10분)
1. L1-01 → L2-05: 단순 질문부터 연도별 추이까지 (워밍업)
2. L3-01 → L3-07: 매출 상위 고객, 배송사 지연율 (비즈니스 가치)
3. C1 멀티턴: 카테고리 → 음료 제품 → 1위 제품 구매 고객 (대화형 드릴다운)
4. L4-05, L4-09: 전월 대비 증감률, 장바구니 분석 (고난도)
5. E-04, E-02: 쓰기 요청 거부, 없는 정보 거절 (안전성)

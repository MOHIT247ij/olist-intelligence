-- Reusable analytics views (PostgreSQL). Power BI can import these directly.

-- 1) Monthly revenue with MoM growth, running total, 3-month moving average
CREATE OR REPLACE VIEW vw_monthly_revenue AS
WITH m AS (
    SELECT date_trunc('month', purchase_date)::date AS month,
           COUNT(*)                                 AS orders,
           COUNT(DISTINCT customer_unique_id)       AS customers,
           SUM(product_revenue)                     AS revenue,
           SUM(gmv)                                 AS gmv,
           SUM(est_gross_profit)                    AS est_gross_profit
    FROM fact_orders
    WHERE order_status NOT IN ('canceled', 'unavailable')
    GROUP BY 1
)
SELECT month, orders, customers, revenue, gmv, est_gross_profit,
       revenue / NULLIF(orders, 0)                                              AS aov,
       ROUND(100.0 * (revenue - LAG(revenue) OVER w) / NULLIF(LAG(revenue) OVER w, 0), 2) AS mom_growth_pct,
       SUM(revenue) OVER (ORDER BY month ROWS UNBOUNDED PRECEDING)             AS running_revenue,
       AVG(revenue) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS revenue_3m_ma
FROM m
WINDOW w AS (ORDER BY month);

-- 2) RFM scores in pure SQL (NTILE quintiles)
CREATE OR REPLACE VIEW vw_rfm AS
WITH ref AS (SELECT MAX(purchase_date) + INTERVAL '1 day' AS ref_date FROM fact_orders),
base AS (
    SELECT o.customer_unique_id,
           EXTRACT(DAY FROM (SELECT ref_date FROM ref) - MAX(o.purchase_date))::int AS recency_days,
           COUNT(DISTINCT o.order_id)                                               AS frequency,
           SUM(o.payment_value)                                                     AS monetary
    FROM fact_orders o
    WHERE o.order_status = 'delivered'
    GROUP BY o.customer_unique_id
)
SELECT *,
       6 - NTILE(5) OVER (ORDER BY recency_days)            AS r_score,
       NTILE(5) OVER (ORDER BY frequency, monetary)         AS f_score,
       NTILE(5) OVER (ORDER BY monetary)                    AS m_score
FROM base;

-- 3) Monthly cohort retention
CREATE OR REPLACE VIEW vw_cohort_retention AS
WITH first_purchase AS (
    SELECT customer_unique_id, date_trunc('month', MIN(purchase_date))::date AS cohort_month
    FROM fact_orders WHERE order_status = 'delivered' GROUP BY 1
),
activity AS (
    SELECT DISTINCT o.customer_unique_id, f.cohort_month,
           (EXTRACT(YEAR FROM age(date_trunc('month', o.purchase_date), f.cohort_month)) * 12
            + EXTRACT(MONTH FROM age(date_trunc('month', o.purchase_date), f.cohort_month)))::int AS month_number
    FROM fact_orders o JOIN first_purchase f USING (customer_unique_id)
    WHERE o.order_status = 'delivered'
)
SELECT cohort_month, month_number,
       COUNT(DISTINCT customer_unique_id) AS active_customers,
       ROUND(100.0 * COUNT(DISTINCT customer_unique_id)
             / FIRST_VALUE(COUNT(DISTINCT customer_unique_id)) OVER (PARTITION BY cohort_month ORDER BY month_number), 2)
             AS retention_pct
FROM activity
GROUP BY cohort_month, month_number;

-- 4) Category performance with Pareto (cumulative revenue share)
CREATE OR REPLACE VIEW vw_category_pareto AS
WITH c AS (
    SELECT category, SUM(price) AS revenue, COUNT(*) AS units, SUM(est_gross_profit) AS est_profit
    FROM fact_order_items WHERE order_status NOT IN ('canceled', 'unavailable')
    GROUP BY category
)
SELECT category, revenue, units, est_profit,
       RANK() OVER (ORDER BY revenue DESC) AS revenue_rank,
       ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
             / SUM(revenue) OVER (), 2)     AS cumulative_share_pct
FROM c;

-- 5) State-level geo KPIs
CREATE OR REPLACE VIEW vw_state_kpis AS
SELECT customer_state AS state,
       COUNT(*)                                   AS orders,
       SUM(product_revenue)                       AS revenue,
       AVG(freight_value / NULLIF(gmv, 0)) * 100  AS freight_share_pct,
       AVG(delivery_days)                         AS avg_delivery_days,
       AVG(is_late::numeric) * 100                AS late_pct,
       AVG(review_score)                          AS avg_review
FROM fact_orders
WHERE order_status = 'delivered'
GROUP BY customer_state;

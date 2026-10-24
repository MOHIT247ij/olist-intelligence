-- Advanced SQL showcase (PostgreSQL). Interview-ready business questions.

-- Q1. Top 3 categories per state by revenue (window + partition)
SELECT * FROM (
    SELECT customer_state, category, SUM(price) AS revenue,
           DENSE_RANK() OVER (PARTITION BY customer_state ORDER BY SUM(price) DESC) AS rnk
    FROM fact_order_items GROUP BY customer_state, category
) t WHERE rnk <= 3 ORDER BY customer_state, rnk;

-- Q2. Does late delivery hurt review score? (conditional aggregation)
SELECT CASE WHEN delay_days <= -10 THEN '1. 10+ days early'
            WHEN delay_days <= 0   THEN '2. On time'
            WHEN delay_days <= 7   THEN '3. 1-7 days late'
            ELSE '4. 7+ days late' END            AS delivery_bucket,
       COUNT(*)                                   AS orders,
       ROUND(AVG(review_score), 2)                AS avg_review,
       ROUND(100.0 * AVG((review_score <= 2)::int), 1) AS pct_negative
FROM fact_orders WHERE order_status = 'delivered' AND review_score IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Q3. Repeat-purchase rate and days to 2nd order (LEAD)
WITH seq AS (
    SELECT customer_unique_id, purchase_date,
           LEAD(purchase_date) OVER (PARTITION BY customer_unique_id ORDER BY purchase_date) AS next_purchase
    FROM fact_orders WHERE order_status = 'delivered'
)
SELECT COUNT(DISTINCT customer_unique_id)                                              AS customers,
       COUNT(DISTINCT customer_unique_id) FILTER (WHERE next_purchase IS NOT NULL)     AS repeat_customers,
       ROUND(100.0 * COUNT(DISTINCT customer_unique_id) FILTER (WHERE next_purchase IS NOT NULL)
             / COUNT(DISTINCT customer_unique_id), 2)                                  AS repeat_rate_pct,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY next_purchase - purchase_date)
             FILTER (WHERE next_purchase IS NOT NULL)                                  AS median_days_to_next
FROM seq;

-- Q4. Seller scorecard: revenue, on-time %, rating, percentile rank
SELECT i.seller_id, s.state,
       SUM(i.price)                                         AS revenue,
       COUNT(DISTINCT i.order_id)                           AS orders,
       ROUND(100 - 100.0 * AVG(o.is_late::numeric), 1)      AS on_time_pct,
       ROUND(AVG(o.review_score), 2)                        AS avg_review,
       ROUND(PERCENT_RANK() OVER (ORDER BY SUM(i.price))::numeric, 3) AS revenue_pctile
FROM fact_order_items i
JOIN fact_orders o USING (order_id)
JOIN dim_seller s USING (seller_id)
WHERE o.order_status = 'delivered'
GROUP BY i.seller_id, s.state
HAVING COUNT(DISTINCT i.order_id) >= 20
ORDER BY revenue DESC LIMIT 25;

-- Q5. Year-over-year same-month comparison
WITH m AS (
    SELECT EXTRACT(YEAR FROM purchase_date)::int AS yr, EXTRACT(MONTH FROM purchase_date)::int AS mon,
           SUM(product_revenue) AS revenue
    FROM fact_orders WHERE order_status NOT IN ('canceled','unavailable') GROUP BY 1, 2
)
SELECT cur.mon, cur.yr, cur.revenue, prev.revenue AS revenue_prev_year,
       ROUND(100.0 * (cur.revenue - prev.revenue) / NULLIF(prev.revenue, 0), 1) AS yoy_pct
FROM m cur LEFT JOIN m prev ON prev.mon = cur.mon AND prev.yr = cur.yr - 1
ORDER BY cur.yr, cur.mon;

-- Q6. Payment behaviour: installments vs AOV
SELECT payment_type,
       CASE WHEN installments <= 1 THEN '1' WHEN installments <= 3 THEN '2-3'
            WHEN installments <= 6 THEN '4-6' ELSE '7+' END AS installment_band,
       COUNT(*) AS orders, ROUND(AVG(payment_value)::numeric, 2) AS avg_order_value
FROM fact_orders GROUP BY 1, 2 ORDER BY 1, 2;

-- Q7. RFM segment summary (uses vw_rfm)
SELECT CASE WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal'
            WHEN r_score >= 4                  THEN 'New / Promising'
            WHEN r_score <= 2 AND m_score >= 4 THEN 'At Risk - High Value'
            WHEN r_score <= 2                  THEN 'Hibernating'
            ELSE 'Needs Attention' END        AS segment,
       COUNT(*) AS customers, ROUND(SUM(monetary)::numeric, 0) AS revenue,
       ROUND(AVG(recency_days)) AS avg_recency
FROM vw_rfm GROUP BY 1 ORDER BY revenue DESC;

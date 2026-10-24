# Power BI — Data Model & DAX Measures

## 1. Connect
**Get Data → PostgreSQL** (`localhost`, db `olist`) → import `fact_orders`, `fact_order_items`, `dim_customer`, `dim_product`, `dim_seller`, `dim_date`, plus views `vw_cohort_retention`, `vw_rfm`.
Also import CSVs from `data/processed/`: `customer_churn_scores.csv`, `customer_rfm.csv`, `forecast_weekly.csv`, `revenue_weekly.csv`.

## 2. Relationships (star schema, single direction)
| From (many) | To (one) |
|---|---|
| fact_orders[date_key] | dim_date[date_key] |
| fact_orders[customer_unique_id] | dim_customer[customer_unique_id] |
| fact_order_items[order_id] | fact_orders[order_id] |
| fact_order_items[product_id] | dim_product[product_id] |
| fact_order_items[seller_id] | dim_seller[seller_id] |
| customer_churn_scores[customer_unique_id] | dim_customer[customer_unique_id] |

Mark `dim_date[date]` as the **Date table**. Create an empty table `_Measures` for all measures.

## 3. Core measures
```DAX
Revenue = CALCULATE ( SUM ( fact_orders[product_revenue] ),
            NOT fact_orders[order_status] IN { "canceled", "unavailable" } )
GMV = CALCULATE ( SUM ( fact_orders[gmv] ), NOT fact_orders[order_status] IN { "canceled", "unavailable" } )
Est Gross Profit = CALCULATE ( SUM ( fact_orders[est_gross_profit] ),
            NOT fact_orders[order_status] IN { "canceled", "unavailable" } )
Est Margin % = DIVIDE ( [Est Gross Profit], [Revenue] )
Orders = CALCULATE ( DISTINCTCOUNT ( fact_orders[order_id] ),
            NOT fact_orders[order_status] IN { "canceled", "unavailable" } )
Customers = CALCULATE ( DISTINCTCOUNT ( fact_orders[customer_unique_id] ),
            NOT fact_orders[order_status] IN { "canceled", "unavailable" } )
AOV = DIVIDE ( [Revenue], [Orders] )
Freight Share % = DIVIDE ( SUM ( fact_orders[freight_value] ), [GMV] )
Cancel Rate % = DIVIDE ( CALCULATE ( COUNTROWS ( fact_orders ),
            fact_orders[order_status] IN { "canceled", "unavailable" } ), COUNTROWS ( fact_orders ) )
```

## 4. Time intelligence
```DAX
Revenue PY = CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( dim_date[date] ) )
Revenue YoY % = DIVIDE ( [Revenue] - [Revenue PY], [Revenue PY] )
Revenue PM = CALCULATE ( [Revenue], DATEADD ( dim_date[date], -1, MONTH ) )
Revenue MoM % = DIVIDE ( [Revenue] - [Revenue PM], [Revenue PM] )
Revenue YTD = TOTALYTD ( [Revenue], dim_date[date] )
Revenue 3M Rolling Avg =
    AVERAGEX ( DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -3, MONTH ), [Revenue] )
```

## 5. Customer & retention
```DAX
Repeat Customers =
    COUNTROWS ( FILTER ( VALUES ( fact_orders[customer_unique_id] ),
        CALCULATE ( DISTINCTCOUNT ( fact_orders[order_id] ) ) > 1 ) )
Repeat Rate % = DIVIDE ( [Repeat Customers], [Customers] )
New Customers =
    COUNTROWS ( FILTER ( VALUES ( fact_orders[customer_unique_id] ),
        CALCULATE ( MIN ( fact_orders[purchase_date] ), ALLEXCEPT ( fact_orders, fact_orders[customer_unique_id] ) )
            >= MIN ( dim_date[date] ) ) )
Revenue per Customer = DIVIDE ( [Revenue], [Customers] )
```

## 6. Churn & risk (from customer_churn_scores)
```DAX
High Risk Customers = CALCULATE ( COUNTROWS ( customer_churn_scores ), customer_churn_scores[risk_tier] = "High" )
Value at Risk = SUM ( customer_churn_scores[value_at_risk] )
Avg Return Probability = AVERAGE ( customer_churn_scores[return_probability] )
```

## 7. Delivery & CX
```DAX
Avg Review = AVERAGE ( fact_orders[review_score] )
Late Delivery % = DIVIDE ( CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[is_late] = 1 ),
            CALCULATE ( COUNTROWS ( fact_orders ), NOT ISBLANK ( fact_orders[is_late] ) ) )
Avg Delivery Days = AVERAGE ( fact_orders[delivery_days] )
Negative Review % = DIVIDE ( CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[review_score] <= 2 ),
            CALCULATE ( COUNTROWS ( fact_orders ), NOT ISBLANK ( fact_orders[review_score] ) ) )
```

## 8. Product / Pareto
```DAX
Item Revenue = SUM ( fact_order_items[price] )
Category Rank = RANKX ( ALL ( dim_product[category] ), [Item Revenue], , DESC, DENSE )
Cumulative Category Share % =
VAR cur = [Item Revenue]
RETURN DIVIDE (
    SUMX ( FILTER ( ALL ( dim_product[category] ), [Item Revenue] >= cur ), [Item Revenue] ),
    CALCULATE ( [Item Revenue], ALL ( dim_product[category] ) ) )
ABC Class = SWITCH ( TRUE (), [Cumulative Category Share %] <= 0.8, "A",
                              [Cumulative Category Share %] <= 0.95, "B", "C" )
```

## 9. Report pages (dashboard spec)
1. **Executive Overview** — KPI cards (Revenue, Est Profit, Orders, AOV, Repeat Rate %, Avg Review), revenue trend line with YoY, slicers: Year / State / Category.
2. **Customers & RFM** — treemap of segments, segment table with recommended action, cohort retention matrix (`vw_cohort_retention`, conditional formatting).
3. **Churn Risk** — High-risk count, Value at Risk, risk-tier donut, top-50 at-risk customer table, drivers bar chart (`churn_feature_importance.csv`).
4. **Sales Forecast** — actual (`revenue_weekly`) + forecast with lower/upper band (`forecast_weekly`).
5. **Products** — Pareto chart (bar + cumulative line), price vs review scatter, ABC matrix.
6. **Geography** — filled map by state (Revenue), bubble map using `dim_customer[lat/lng]`, Delivery days vs Review by state.
7. **Operations & CX** — Late Delivery %, delivery bucket vs review, seller scorecard.

Theme tip: one accent colour, grey for context, max 6 visuals per page, drill-through from Executive → Customer detail.

## 10. New tables from the advanced pipeline (import from `data/processed/`)
| File | Use in Power BI |
|---|---|
| `agg_cohort_retention.csv` | Matrix: rows `cohort_month`, columns `month_number`, values `retention_pct` (conditional formatting = heatmap) |
| `customer_clv.csv` | Relate on `customer_unique_id` → CLV tier slicer, Top-N customers table |
| `agg_seller_scorecard.csv` | Seller page: scatter `late_pct` vs `avg_review`, size = `revenue`, legend = `tier` |
| `review_sentiment.csv` | Relate on `order_id` → sentiment donut, sentiment by `customer_state` |
| `agg_complaint_themes.csv` | Bar chart of complaint themes |
| `agg_market_basket.csv` | Table of category pairs with `lift` |
| `agg_revenue_anomalies.csv` | Line (revenue vs expected) + markers where `alert` is not blank |

```DAX
Avg CLV = AVERAGE ( customer_clv[total_clv] )
Platinum Customers = CALCULATE ( COUNTROWS ( customer_clv ), customer_clv[clv_tier] = "Platinum" )
Negative Review % = DIVIDE ( CALCULATE ( COUNTROWS ( review_sentiment ), review_sentiment[sentiment] = "negative" ),
                             COUNTROWS ( review_sentiment ) )
Top Sellers = CALCULATE ( COUNTROWS ( agg_seller_scorecard ), agg_seller_scorecard[tier] = "Top Seller" )
```

# 🎨 Attractive Power BI Dashboard — Build Guide

Canvas: **1280 × 720** (default 16:9). Every position below is in pixels: set it in **Format → General → Properties → Size & position**.

## One-time setup
1. **View → Themes → Browse for themes** → `powerbi/Olist_Dark_Theme.json`
2. Create 5 pages and name them: Executive Overview, Customers & RFM, Sales & Forecast, Products & Sellers, Delivery & Reviews
3. On each page: click empty canvas → **Format page → Canvas background** → *Browse* → pick that page's PNG from `powerbi/backgrounds/` → **Image fit: Fit**, **Transparency: 0%**. Also set **Wallpaper** colour `#0B1220`.
4. For every visual: **Background OFF, Title OFF** (the title is printed in the background image), **Visual border OFF**.
5. **Page buttons**: Insert → Buttons → Blank, place over each page name in the left sidebar (x=12, w=186, h=28, y = 110/144/178/212/246), Action → *Page navigation* → that page, button fill OFF.
6. **Slicers** (Year, State, Category): place over the three filter boxes (x=14, w=182, h=34, y=336/402/468), style *Dropdown*, header OFF. Select all 3 → View → **Sync slicers** → all pages.
7. **KPI cards**: use the new *Card* visual, label OFF; place inside each card box (start 16 px right of the left edge, 28 px below the top).

## Page: Executive Overview  (`backgrounds/01_executive.png`)

| Visual | Type | Fields | X | Y | W | H |
|---|---|---|---|---|---|---|
| KPI · Revenue | Card | [Revenue] | 240 | 114 | 173 | 58 |
| KPI · Est. Profit | Card | [Est Gross Profit] | 451 | 114 | 173 | 58 |
| KPI · Orders | Card | [Orders] | 662 | 114 | 173 | 58 |
| KPI · Avg Order Value | Card | [AOV] | 874 | 114 | 173 | 58 |
| KPI · Avg Review | Card | [Avg Review] | 1085 | 114 | 173 | 58 |
| Monthly revenue & 3-month average | Line + clustered column chart | X: dim_date[year_month] · Column: [Revenue] · Line: [Revenue 3M Rolling Avg] | 232 | 222 | 631 | 224 |
| Revenue by payment type | Donut chart | Legend: fact_orders[payment_type] · Values: [Revenue] | 893 | 222 | 365 | 224 |
| Top 10 categories | Bar chart (Top N = 10) | Y: dim_product[category] · X: [Item Revenue] | 232 | 498 | 322 | 200 |
| Revenue by state | Bar chart | Y: fact_orders[customer_state] · X: [Revenue] (Top 10) | 584 | 498 | 322 | 200 |
| Late delivery vs review | Column chart | X: delivery bucket column (see DAX) · Y: [Avg Review] | 936 | 498 | 322 | 200 |

## Page: Customers & RFM  (`backgrounds/02_customers.png`)

| Visual | Type | Fields | X | Y | W | H |
|---|---|---|---|---|---|---|
| KPI · Customers | Card | [Customers] | 240 | 114 | 173 | 58 |
| KPI · Repeat Rate % | Card | [Repeat Rate %] | 451 | 114 | 173 | 58 |
| KPI · At-Risk Customers | Card | [At Risk Customers] | 662 | 114 | 173 | 58 |
| KPI · Avg CLV | Card | [Avg CLV] | 874 | 114 | 173 | 58 |
| KPI · Month-1 Retention | Card | [Month1 Retention %] | 1085 | 114 | 173 | 58 |
| RFM segments (treemap) | Treemap | Category: customer_rfm[segment] · Values: Count of customer_unique_id | 232 | 222 | 545 | 224 |
| Segment table & actions | Table | customer_rfm[segment], customers, Sum monetary, recommended_action | 807 | 222 | 451 | 224 |
| Cohort retention matrix | Matrix (heatmap) | Rows: agg_cohort_retention[cohort_month] · Columns: month_number · Values: retention_pct + conditional formatting (background color scale) | 232 | 498 | 617 | 200 |
| Churn drivers | Bar chart | Y: churn_feature_importance[feature] · X: importance | 879 | 498 | 379 | 200 |

## Page: Sales & Forecast  (`backgrounds/03_sales_forecast.png`)

| Visual | Type | Fields | X | Y | W | H |
|---|---|---|---|---|---|---|
| KPI · Revenue YTD | Card | [Revenue YTD] | 240 | 114 | 173 | 58 |
| KPI · MoM Growth % | Card | [Revenue MoM %] | 451 | 114 | 173 | 58 |
| KPI · YoY Growth % | Card | [Revenue YoY %] | 662 | 114 | 173 | 58 |
| KPI · Next 12 Weeks (Forecast) | Card | [Forecast Next 12W] | 874 | 114 | 173 | 58 |
| KPI · Forecast Error (MAPE) | Card | [Forecast MAPE] | 1085 | 114 | 173 | 58 |
| Weekly revenue: actual vs forecast | Line chart | X: week (revenue_weekly + forecast_weekly appended, see guide) · Y: actual, forecast, lower, upper | 232 | 222 | 1026 | 245 |
| Revenue by weekday | Column chart | X: dim_date[day_name] · Y: [Revenue] | 232 | 519 | 322 | 179 |
| Revenue by month (YoY) | Line chart | X: dim_date[month_name] · Y: [Revenue] · Legend: dim_date[year] | 584 | 519 | 322 | 179 |
| Anomaly alerts | Table | agg_revenue_anomalies: week, revenue, change_pct, alert (filter alert is not blank) | 936 | 519 | 322 | 179 |

## Page: Products & Sellers  (`backgrounds/04_products_sellers.png`)

| Visual | Type | Fields | X | Y | W | H |
|---|---|---|---|---|---|---|
| KPI · Categories | Card | [Category Count] | 240 | 114 | 173 | 58 |
| KPI · Top Category Share | Card | [Top Category Share %] | 451 | 114 | 173 | 58 |
| KPI · Sellers | Card | [Seller Count] | 662 | 114 | 173 | 58 |
| KPI · Top Sellers | Card | [Top Sellers] | 874 | 114 | 173 | 58 |
| KPI · Avg Seller Score | Card | [Avg Seller Score] | 1085 | 114 | 173 | 58 |
| Pareto: category revenue & cumulative % | Line + clustered column chart (Pareto) | X: dim_product[category] · Column: [Item Revenue] · Line: [Cumulative Category Share %] | 232 | 222 | 584 | 212 |
| Price vs review (bubble) | Scatter chart | X: avg price · Y: avg review · Size: revenue · Details: category (agg_category) | 846 | 222 | 412 | 212 |
| Seller scorecard | Table | agg_seller_scorecard: seller_id, state, revenue, avg_review, late_pct, score, tier (conditional icons on score) | 232 | 486 | 565 | 212 |
| Seller tiers | Donut chart | Legend: agg_seller_scorecard[tier] · Values: Count of seller_id | 827 | 486 | 431 | 212 |

## Page: Delivery & Reviews  (`backgrounds/05_delivery_reviews.png`)

| Visual | Type | Fields | X | Y | W | H |
|---|---|---|---|---|---|---|
| KPI · Avg Delivery Days | Card | [Avg Delivery Days] | 240 | 114 | 173 | 58 |
| KPI · Late Deliveries % | Card | [Late Delivery %] | 451 | 114 | 173 | 58 |
| KPI · Avg Review | Card | [Avg Review] | 662 | 114 | 173 | 58 |
| KPI · Negative Reviews % | Card | [Negative Review %] | 874 | 114 | 173 | 58 |
| KPI · Positive Sentiment % | Card | [Positive Sentiment %] | 1085 | 114 | 173 | 58 |
| Delivery delay vs review | Column chart | X: delivery bucket · Y: [Avg Review] and [Negative Review %] | 232 | 222 | 451 | 212 |
| Avg delivery days by state (map) | Filled map / Azure map | Location: dim_customer[state] & 'Brazil' · Color: [Avg Delivery Days] | 713 | 222 | 545 | 212 |
| Complaint themes | Bar chart | Y: agg_complaint_themes[theme] · X: complaints | 232 | 486 | 498 | 212 |
| Sentiment trend by month | Area chart (100% stacked) | X: agg_sentiment_month[review_month] · Y: positive_pct, neutral_pct, negative_pct | 760 | 486 | 498 | 212 |

## Extra DAX for these pages (add to `_Measures`)
```DAX
Est Gross Profit = SUM ( fact_orders[est_gross_profit] )
Avg Review = AVERAGE ( fact_orders[review_score] )
At Risk Customers = CALCULATE ( COUNTROWS ( customer_rfm ), customer_rfm[segment] = "At Risk" )
Avg CLV = AVERAGE ( customer_clv[total_clv] )
Month1 Retention % = DIVIDE ( CALCULATE ( AVERAGE ( agg_cohort_retention[retention_pct] ), agg_cohort_retention[month_number] = 1 ), 100 )
Forecast Next 12W = SUM ( forecast_weekly[forecast] )
Forecast MAPE = 0.148   -- from reports/summary.json (model_mape_pct / 100); update after each pipeline run
Category Count = DISTINCTCOUNT ( dim_product[category] )
Top Category Share % = DIVIDE ( MAXX ( VALUES ( dim_product[category] ), [Item Revenue] ), [Item Revenue] )
Seller Count = DISTINCTCOUNT ( fact_order_items[seller_id] )
Top Sellers = CALCULATE ( COUNTROWS ( agg_seller_scorecard ), agg_seller_scorecard[tier] = "Top Seller" )
Avg Seller Score = AVERAGE ( agg_seller_scorecard[score] )
Avg Delivery Days = AVERAGE ( fact_orders[delivery_days] )
Positive Sentiment % = DIVIDE ( CALCULATE ( COUNTROWS ( review_sentiment ), review_sentiment[sentiment] = "positive" ), COUNTROWS ( review_sentiment ) )

-- Calculated COLUMN on fact_orders (Modeling → New column):
Delivery Bucket = SWITCH ( TRUE (), ISBLANK ( fact_orders[delay_days] ), BLANK (),
    fact_orders[delay_days] <= -10, "1. 10+ days early", fact_orders[delay_days] <= 0, "2. On time",
    fact_orders[delay_days] <= 7, "3. 1-7 days late", "4. 7+ days late" )
```

## Forecast chart data (Power Query)
Home → Transform data → **Append Queries as New**: `revenue_weekly` + `forecast_weekly` → rename `revenue` to *Actual*. Use `week` on X and Actual / forecast / lower / upper as lines (lower & upper: light dashed).

## Polish checklist ✨
- Numbers: display units **Millions** with 1 decimal for revenue cards, `R$` prefix (Format → Callout value → Display units)
- Max **6 visuals per page**, consistent gaps (already in the background)
- Conditional formatting: green/red arrows on MoM/YoY cards, data bars in tables, colour scale on the cohort matrix
- Tooltips ON; turn **Edit interactions** to *Filter* between charts
- Add a small text box at the bottom of each page with ONE insight sentence (e.g., *7+ days late → review falls from 4.3★ to 1.7★*)
- Export screenshots for GitHub: File → Export → PDF, or Win + Shift + S
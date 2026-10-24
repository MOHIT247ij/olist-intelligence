"""End-to-end pipeline: ETL -> analytics -> RFM -> churn -> forecast -> outputs for Power BI & app.

  python pipeline.py              # full run (ETL + models)
  python pipeline.py --skip-etl   # reuse data/processed
  python pipeline.py --ai-report  # also generate Gemini executive report (needs GEMINI_API_KEY)
"""
import argparse
import json
import logging

import pandas as pd

from src import advanced, analytics, churn, config, etl, forecast, rfm, sentiment

log = logging.getLogger("pipeline")


def _step(name, fn, errors: dict):
    """Run one analysis step; never let one failing feature kill the whole pipeline."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        errors[name] = f"{type(e).__name__}: {str(e)[:200]}"
        log.warning("step '%s' skipped: %s", name, errors[name])
        return None


def run_analytics(orders: pd.DataFrame, items: pd.DataFrame, sellers_dim: pd.DataFrame | None,
                  reviews_raw: pd.DataFrame | None, out, reports_dir, meta: dict | None = None) -> dict:
    """All analytics on star-schema tables -> CSVs in `out` + summary.json in `reports_dir`.
    Used for the Olist data AND for any uploaded dataset (see src/universal.py)."""
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    errors: dict = {}
    summary: dict = {"meta": meta or {"dataset": "Olist Brazilian E-Commerce", "currency": "R$"}}
    caps = (meta or {}).get("capabilities")
    ok = lambda cap: caps is None or caps.get(cap, True)  # noqa: E731

    # 1. Revenue / product / geo
    k = analytics.kpis(orders)
    summary["kpis"] = k
    analytics.monthly_revenue(orders).to_csv(out / "agg_monthly_revenue.csv", index=False)
    cats = _step("products", lambda: analytics.category_performance(items, orders), errors) \
        if ok("Products & Pareto") else None
    if cats is not None:
        cats.to_csv(out / "agg_category.csv", index=False)
        summary["top_categories"] = cats.head(10)[["category", "revenue", "revenue_share_pct", "avg_review"]] \
            .to_dict("records")
    if ok("Geography"):
        _step("geography", lambda: analytics.state_performance(orders).to_csv(out / "agg_state.csv", index=False),
              errors)
    dvr = _step("delivery", lambda: analytics.delivery_vs_review(orders), errors) \
        if ok("Delivery & what-if") else None
    if dvr is not None:
        dvr.to_csv(out / "agg_delivery_review.csv", index=False)
        summary["delivery_vs_review"] = dvr.to_dict("records")
    if orders["payment_type"].nunique() > 1 or caps is None:
        _step("payments", lambda: analytics.payment_mix(orders).to_csv(out / "agg_payment.csv", index=False),
              errors)
    log.info("KPIs: %s", {a: round(b, 2) for a, b in k.items()})

    # 2. RFM
    cust_ok = ok("RFM / Cohorts / CLV / Churn")
    r = _step("rfm", lambda: rfm.kmeans_clusters(rfm.compute_rfm(orders)), errors) if cust_ok else None
    if r is not None:
        r.to_csv(out / "customer_rfm.csv", index=False)
        seg = rfm.segment_summary(r)
        seg.to_csv(out / "agg_rfm_segments.csv", index=False)
        summary["rfm_segments"] = seg[["segment", "customers", "revenue_share_pct", "recommended_action"]] \
            .to_dict("records")

    # 3. Churn
    scored = None
    ch = _step("churn", lambda: churn.train(orders, items), errors) if cust_ok else None
    if ch is not None:
        ch["feature_importance"].to_csv(out / "churn_feature_importance.csv", index=False)
        scored = churn.score_customers(ch["model"], orders, items, r)
        scored.to_csv(out / "customer_churn_scores.csv", index=False)
        summary["churn"] = {"cutoff": ch["cutoff"], "churn_rate": ch["churn_rate"], "best_model": ch["best_model"],
                            "metrics": ch["metrics"], "top_drivers": ch["feature_importance"].head(6).to_dict("records")}
        log.info("Churn: best=%s %s", ch["best_model"], ch["metrics"][ch["best_model"]])

    # 4. Forecast
    fc = _step("forecast", lambda: forecast.forecast(forecast.weekly_series(orders), horizon=12), errors)
    if fc is not None:
        fc["forecast"].rename_axis("week").reset_index().to_csv(out / "forecast_weekly.csv", index=False)
        fc["history"].rename_axis("week").reset_index().to_csv(out / "revenue_weekly.csv", index=False)
        bt = fc["backtest"]
        summary["forecast"] = {"next_12w_revenue": float(fc["forecast"]["forecast"].sum()),
                               "model_mape_pct": bt["model_mape_pct"], "baseline_mape_pct": bt["baseline_mape_pct"]}
        log.info("Forecast MAPE model=%.1f%% baseline=%.1f%%", bt["model_mape_pct"], bt["baseline_mape_pct"])
        an = _step("anomalies", lambda: advanced.revenue_anomalies(fc["history"]), errors)
        if an is not None:
            an.to_csv(out / "agg_revenue_anomalies.csv", index=False)
            summary["anomalies"] = an[an["alert"] != ""].tail(5)[["week", "revenue", "change_pct", "alert"]] \
                .to_dict("records")

    # 5. Advanced analytics
    cohort = _step("cohort", lambda: advanced.cohort_retention(orders), errors) if cust_ok else None
    if cohort is not None:
        cohort.to_csv(out / "agg_cohort_retention.csv", index=False)
        m1 = cohort[cohort["month_number"] == 1]["retention_pct"]
        summary["cohort"] = {"avg_month1_retention_pct": float(m1.mean()) if len(m1) else None}
    basket = _step("basket", lambda: advanced.market_basket(items), errors) if ok("Market basket") else None
    if basket is not None:
        basket.to_csv(out / "agg_market_basket.csv", index=False)
        summary["market_basket"] = {**advanced.basket_stats(items),
                                    "top_pairs": basket.head(5)[["category_a", "category_b", "orders_together",
                                                                 "lift"]].to_dict("records")}
    clv = _step("clv", lambda: advanced.customer_clv(orders, scored), errors) if cust_ok else None
    if clv is not None:
        clv.to_csv(out / "customer_clv.csv", index=False)
        tiers = advanced.clv_summary(clv)
        tiers.to_csv(out / "agg_clv_tiers.csv", index=False)
        summary["clv"] = {"expected_orders_if_return_12m": clv.attrs.get("expected_orders_if_return"),
                          "tiers": tiers.to_dict("records")}
    sellers = _step("sellers", lambda: advanced.seller_scorecard(items, orders, sellers_dim), errors) \
        if ok("Seller scorecard") else None
    if sellers is not None and len(sellers):
        sellers.to_csv(out / "agg_seller_scorecard.csv", index=False)
        summary["sellers"] = {"scored_sellers": int(len(sellers)),
                              "tier_counts": sellers["tier"].value_counts().to_dict()}
    wi = _step("what_if", lambda: advanced.what_if_baseline(orders), errors) if ok("Delivery & what-if") else None
    if wi is not None and wi.get("orders"):
        summary["what_if_baseline"] = wi

    # 6. Review sentiment
    if reviews_raw is not None and len(reviews_raw) and ok("Reviews & sentiment"):
        sa = _step("sentiment", lambda: sentiment.analyze(reviews_raw, orders), errors)
        if sa is not None:
            sa.drop(columns=["text"]).to_csv(out / "review_sentiment.csv", index=False)
            sentiment.sentiment_by_month(sa).to_csv(out / "agg_sentiment_month.csv", index=False)
            themes = sentiment.complaint_themes(sa)
            themes.to_csv(out / "agg_complaint_themes.csv", index=False)
            (out / "negative_review_samples.json").write_text(
                json.dumps(sentiment.negative_samples(sa), ensure_ascii=False, indent=1), encoding="utf-8")
            summary["sentiment"] = {"share_pct": (sa["sentiment"].value_counts(normalize=True) * 100).round(1)
                                    .to_dict(), "reviews_with_text_pct": float(sa["has_text"].mean() * 100),
                                    "top_complaint_themes": themes.head(5).to_dict("records")}
            log.info("Sentiment: %s", summary["sentiment"]["share_pct"])

    summary["unavailable"] = errors
    (reports_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("Outputs written to %s and %s (skipped: %s)", out, reports_dir, list(errors) or "none")
    return summary


def main(skip_etl: bool = False, ai_report: bool = False):
    if not skip_etl:
        etl.run()
    orders = etl.read_processed("fact_orders")
    items = etl.read_processed("fact_order_items")
    reviews_file = config.RAW_DIR / config.RAW_FILES["reviews"]
    reviews_raw = pd.read_csv(reviews_file) if reviews_file.exists() else None
    summary = run_analytics(orders, items, etl.read_processed("dim_seller"), reviews_raw,
                            config.PROCESSED_DIR, config.REPORTS_DIR)
    if ai_report:
        from src.ai import insights
        path = insights.generate_report(summary)
        log.info("AI report: %s", path)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-etl", action="store_true")
    ap.add_argument("--ai-report", action="store_true")
    a = ap.parse_args()
    main(a.skip_etl, a.ai_report)

"""Advanced analytics: cohort retention, market basket, CLV, seller scorecard, anomaly alerts, what-if baseline."""
from itertools import combinations

import numpy as np
import pandas as pd

EXCLUDE = ("canceled", "unavailable")


def _delivered(orders):
    return orders[orders["order_status"] == "delivered"]


# ---------------------------------------------------------------- 5. Cohort retention
def cohort_retention(orders: pd.DataFrame, max_months: int = 12) -> pd.DataFrame:
    """Long table: cohort_month, month_number, customers, retention_pct (month 0 = 100%)."""
    d = _delivered(orders)[["customer_unique_id", "purchase_date"]].copy()
    d["order_month"] = d["purchase_date"].dt.to_period("M")
    d["cohort"] = d.groupby("customer_unique_id")["order_month"].transform("min")
    d["month_number"] = (d["order_month"] - d["cohort"]).apply(lambda x: x.n)
    d = d[d["month_number"] <= max_months]
    g = d.groupby(["cohort", "month_number"])["customer_unique_id"].nunique().rename("customers").reset_index()
    size = g[g["month_number"] == 0].set_index("cohort")["customers"]
    g["cohort_size"] = g["cohort"].map(size)
    g["retention_pct"] = g["customers"] / g["cohort_size"] * 100
    g = g[g["cohort_size"] >= 50]                      # ignore tiny early cohorts (2016)
    g["cohort_month"] = g["cohort"].astype(str)
    return g.drop(columns="cohort")


def cohort_matrix(long: pd.DataFrame) -> pd.DataFrame:
    return long.pivot(index="cohort_month", columns="month_number", values="retention_pct").round(2)


# ---------------------------------------------------------------- 6. Market basket (category level)
def market_basket(items: pd.DataFrame, min_pair_orders: int = 5) -> pd.DataFrame:
    """Category pairs bought in the same order: support, confidence (both directions), lift."""
    it = items[~items["order_status"].isin(EXCLUDE)][["order_id", "category"]].dropna().drop_duplicates()
    n_orders = it["order_id"].nunique()
    cat_orders = it.groupby("category")["order_id"].nunique()
    multi = it.groupby("order_id")["category"].apply(lambda s: sorted(set(s)))
    multi = multi[multi.str.len() >= 2]
    counts: dict = {}
    for cats in multi:
        for a, b in combinations(cats, 2):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    rows = []
    for (a, b), c in counts.items():
        if c < min_pair_orders:
            continue
        sa, sb = cat_orders[a] / n_orders, cat_orders[b] / n_orders
        sup = c / n_orders
        rows.append({"category_a": a, "category_b": b, "orders_together": c, "support_pct": sup * 100,
                     "confidence_a_to_b_pct": c / cat_orders[a] * 100, "confidence_b_to_a_pct": c / cat_orders[b] * 100,
                     "lift": sup / (sa * sb)})
    cols = ["category_a", "category_b", "orders_together", "support_pct", "confidence_a_to_b_pct",
            "confidence_b_to_a_pct", "lift"]
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["lift", "orders_together"], ascending=False).reset_index(drop=True)


def basket_stats(items: pd.DataFrame) -> dict:
    it = items[~items["order_status"].isin(EXCLUDE)]
    per = it.groupby("order_id").agg(n_items=("order_item_id", "count"), n_cats=("category", "nunique"))
    return {"orders": int(len(per)), "multi_item_pct": float((per["n_items"] > 1).mean() * 100),
            "multi_category_pct": float((per["n_cats"] > 1).mean() * 100)}


# ---------------------------------------------------------------- 7. Customer Lifetime Value
def customer_clv(orders: pd.DataFrame, churn_scores: pd.DataFrame | None = None,
                 horizon_months: int = 12) -> pd.DataFrame:
    """Historical CLV + simple predictive 12-month value.

    predicted_12m_value = return_probability x avg_order_value x expected_orders_if_return
    (expected_orders_if_return = average yearly orders of customers who did come back).
    Heuristic, transparent model -- explainable in interviews (vs black-box BG/NBD).
    """
    d = _delivered(orders)
    c = d.groupby("customer_unique_id").agg(orders=("order_id", "nunique"), historical_value=("payment_value", "sum"),
                                            first=("purchase_date", "min"), last=("purchase_date", "max"),
                                            state=("customer_state", "first"))
    c["avg_order_value"] = c["historical_value"] / c["orders"]
    rep = c[c["orders"] > 1]
    span_years = ((rep["last"] - rep["first"]).dt.days / 365).clip(lower=0.25)
    exp_orders = float(((rep["orders"] - 1) / span_years).median()) if len(rep) else 1.0
    exp_orders = float(np.clip(exp_orders * horizon_months / 12, 0.5, 6))
    if churn_scores is not None and "return_probability" in churn_scores:
        p = churn_scores.set_index("customer_unique_id")["return_probability"]
        c["return_probability"] = p.reindex(c.index).fillna(p.median() if len(p) else 0.03)
    else:
        c["return_probability"] = (c["orders"] > 1).mean()
    c["predicted_12m_value"] = c["return_probability"] * c["avg_order_value"] * exp_orders
    c["total_clv"] = c["historical_value"] + c["predicted_12m_value"]
    c["clv_tier"] = pd.qcut(c["total_clv"].rank(method="first"), 4, labels=["Bronze", "Silver", "Gold", "Platinum"])
    c.attrs["expected_orders_if_return"] = exp_orders
    return c.drop(columns=["first", "last"]).reset_index()


def clv_summary(clv: pd.DataFrame) -> pd.DataFrame:
    s = clv.groupby("clv_tier", observed=True).agg(customers=("customer_unique_id", "count"),
                                                   avg_clv=("total_clv", "mean"), total_clv=("total_clv", "sum"),
                                                   avg_orders=("orders", "mean"))
    s["clv_share_pct"] = s["total_clv"] / s["total_clv"].sum() * 100
    return s.reset_index()


# ---------------------------------------------------------------- 8. Seller scorecard
def seller_scorecard(items: pd.DataFrame, orders: pd.DataFrame, sellers: pd.DataFrame | None = None,
                     min_orders: int = 10) -> pd.DataFrame:
    o = orders.set_index("order_id")[["review_score", "is_late", "delivery_days", "order_status"]]
    it = items.join(o.drop(columns="order_status"), on="order_id")
    it = it[~it["order_status"].isin(EXCLUDE)]
    s = it.groupby("seller_id").agg(revenue=("price", "sum"), orders=("order_id", "nunique"),
                                    items_sold=("order_item_id", "count"), categories=("category", "nunique"),
                                    avg_review=("review_score", "mean"),
                                    late_pct=("is_late", lambda x: pd.to_numeric(x, errors="coerce").mean() * 100),
                                    avg_delivery_days=("delivery_days", "mean"))
    s = s[s["orders"] >= min_orders].copy()
    if s.empty:
        return s.reset_index()
    pr = lambda col, asc=True: s[col].rank(pct=True, ascending=asc).fillna(0.5)  # noqa: E731
    s["score"] = (0.35 * pr("avg_review") + 0.25 * pr("late_pct", asc=False) + 0.25 * pr("revenue")
                  + 0.15 * pr("avg_delivery_days", asc=False)) * 100
    s["tier"] = pd.cut(s["score"], [-1, 40, 60, 80, 101], labels=["Needs Improvement", "Average", "Good", "Top Seller"])
    s = s.reset_index()
    if sellers is not None:
        sd = sellers[["seller_id", "city", "state"]].copy()
        sd["seller_id"], s["seller_id"] = sd["seller_id"].astype(str), s["seller_id"].astype(str)
        s = s.merge(sd.drop_duplicates("seller_id"), on="seller_id", how="left")
    return s.sort_values("score", ascending=False)


# ---------------------------------------------------------------- 10. Anomaly alerts
def revenue_anomalies(weekly: pd.Series, window: int = 8, z: float = 2.5) -> pd.DataFrame:
    df = weekly.rename("revenue").to_frame()
    base = df["revenue"].shift(1).rolling(window, min_periods=4)
    df["expected"] = base.mean()
    df["std"] = base.std()
    df["z_score"] = (df["revenue"] - df["expected"]) / df["std"].replace(0, np.nan)
    df["change_pct"] = (df["revenue"] / df["expected"] - 1) * 100
    df["alert"] = np.where(df["z_score"] >= z, "Spike", np.where(df["z_score"] <= -z, "Drop", ""))
    return df.rename_axis("week").reset_index()


# ---------------------------------------------------------------- 11. What-if baseline
def what_if_baseline(orders: pd.DataFrame) -> dict:
    d = _delivered(orders).dropna(subset=["is_late"])
    d = d.assign(is_late=d["is_late"].astype(float))
    late, ontime = d[d["is_late"] == 1], d[d["is_late"] == 0]
    cust = _delivered(orders).groupby("customer_unique_id").agg(n=("order_id", "nunique"),
                                                                first_late=("is_late", "first"))
    cust["first_late"] = pd.to_numeric(cust["first_late"], errors="coerce")
    rep = lambda g: float((g["n"] > 1).mean() * 100) if len(g) else 0.0  # noqa: E731
    return {
        "orders": int(len(d)), "late_pct": float(d["is_late"].mean() * 100),
        "review_late": float(late["review_score"].mean()), "review_ontime": float(ontime["review_score"].mean()),
        "neg_late_pct": float((late["review_score"] <= 2).mean() * 100),
        "neg_ontime_pct": float((ontime["review_score"] <= 2).mean() * 100),
        "repeat_late_pct": rep(cust[cust["first_late"] == 1]), "repeat_ontime_pct": rep(cust[cust["first_late"] == 0]),
        "aov": float(d["product_revenue"].mean()),
        "customers": int(_delivered(orders)["customer_unique_id"].nunique()),
    }


def simulate(base: dict, late_reduction_pct: float) -> dict:
    """Move `late_reduction_pct`% of late orders to on-time; recompute expected review, negatives, repeat buyers."""
    lp = base["late_pct"] / 100
    new_lp = lp * (1 - late_reduction_pct / 100)
    mix = lambda a, b, p: p * a + (1 - p) * b  # noqa: E731
    cur_rev, new_rev = (mix(base["review_late"], base["review_ontime"], x) for x in (lp, new_lp))
    cur_neg, new_neg = (mix(base["neg_late_pct"], base["neg_ontime_pct"], x) for x in (lp, new_lp))
    cur_rep, new_rep = (mix(base["repeat_late_pct"], base["repeat_ontime_pct"], x) for x in (lp, new_lp))
    extra_buyers = (new_rep - cur_rep) / 100 * base["customers"]
    return {"late_pct": (lp * 100, new_lp * 100), "avg_review": (cur_rev, new_rev),
            "negative_review_pct": (cur_neg, new_neg), "repeat_rate_pct": (cur_rep, new_rep),
            "extra_repeat_customers": extra_buyers, "extra_revenue": extra_buyers * base["aov"],
            "fewer_negative_reviews": (cur_neg - new_neg) / 100 * base["orders"]}

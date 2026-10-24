"""Descriptive analytics: revenue & profit, product/category, geography, delivery/CX."""
import pandas as pd

EXCLUDE_STATUS = ("canceled", "unavailable")


def _valid(orders: pd.DataFrame) -> pd.DataFrame:
    return orders[~orders["order_status"].isin(EXCLUDE_STATUS)]


# ------------------------------------------------------------ Revenue & profit
def kpis(orders: pd.DataFrame) -> dict:
    v = _valid(orders)
    d = orders[orders["order_status"] == "delivered"]
    cust_orders = v.groupby("customer_unique_id")["order_id"].nunique()
    return {
        "revenue": float(v["product_revenue"].sum()),
        "gmv": float(v["gmv"].sum()),
        "est_gross_profit": float(v["est_gross_profit"].sum()),
        "orders": int(v["order_id"].nunique()),
        "customers": int(v["customer_unique_id"].nunique()),
        "aov": float(v["product_revenue"].sum() / max(v["order_id"].nunique(), 1)),
        "repeat_customer_rate_pct": float((cust_orders > 1).mean() * 100),
        "cancel_rate_pct": float(orders["order_status"].isin(EXCLUDE_STATUS).mean() * 100),
        "avg_review": float(d["review_score"].mean()),
        "late_delivery_pct": float(d["is_late"].astype(float).mean() * 100),
        "avg_delivery_days": float(d["delivery_days"].mean()),
        "freight_share_pct": float(v["freight_value"].sum() / max(v["gmv"].sum(), 1) * 100),
    }


def monthly_revenue(orders: pd.DataFrame) -> pd.DataFrame:
    v = _valid(orders).assign(month=lambda x: x["purchase_date"].dt.to_period("M").dt.to_timestamp())
    m = v.groupby("month").agg(orders=("order_id", "nunique"), customers=("customer_unique_id", "nunique"),
                               revenue=("product_revenue", "sum"), gmv=("gmv", "sum"),
                               est_gross_profit=("est_gross_profit", "sum")).reset_index()
    m["aov"] = m["revenue"] / m["orders"]
    m["mom_growth_pct"] = m["revenue"].pct_change() * 100
    m["revenue_3m_ma"] = m["revenue"].rolling(3, min_periods=1).mean()
    return m


# ------------------------------------------------------------ Product & category
def category_performance(items: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    it = items[~items["order_status"].isin(EXCLUDE_STATUS)]
    rev = orders.set_index("order_id")["review_score"]
    it = it.assign(review_score=it["order_id"].map(rev))
    c = it.groupby("category").agg(revenue=("price", "sum"), units=("order_item_id", "count"),
                                   orders=("order_id", "nunique"), avg_price=("price", "mean"),
                                   avg_freight=("freight_value", "mean"), est_profit=("est_gross_profit", "sum"),
                                   avg_review=("review_score", "mean")).sort_values("revenue", ascending=False)
    c["revenue_share_pct"] = c["revenue"] / c["revenue"].sum() * 100
    c["cumulative_share_pct"] = c["revenue_share_pct"].cumsum()
    c["pareto_class"] = pd.cut(c["cumulative_share_pct"], [0, 80, 95, 100.001], labels=["A", "B", "C"])
    return c.reset_index()


def top_products(items: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return (items.groupby(["product_id", "category"]).agg(revenue=("price", "sum"), units=("order_item_id", "count"))
            .sort_values("revenue", ascending=False).head(n).reset_index())


# ------------------------------------------------------------ Geography
def state_performance(orders: pd.DataFrame) -> pd.DataFrame:
    d = orders[orders["order_status"] == "delivered"]
    s = d.groupby("customer_state").agg(orders=("order_id", "nunique"), customers=("customer_unique_id", "nunique"),
                                        revenue=("product_revenue", "sum"), avg_freight=("freight_value", "mean"),
                                        avg_delivery_days=("delivery_days", "mean"),
                                        late_pct=("is_late", lambda x: x.astype(float).mean() * 100),
                                        avg_review=("review_score", "mean"))
    s["revenue_share_pct"] = s["revenue"] / s["revenue"].sum() * 100
    return s.sort_values("revenue", ascending=False).reset_index().rename(columns={"customer_state": "state"})


# ------------------------------------------------------------ Delivery -> satisfaction
def delivery_vs_review(orders: pd.DataFrame) -> pd.DataFrame:
    d = orders[(orders["order_status"] == "delivered") & orders["review_score"].notna()].copy()
    d["delivery_bucket"] = pd.cut(d["delay_days"], [-1e9, -10, 0, 7, 1e9],
                                  labels=["10+ days early", "On time", "1-7 days late", "7+ days late"])
    return (d.groupby("delivery_bucket", observed=True)
            .agg(orders=("order_id", "count"), avg_review=("review_score", "mean"),
                 pct_negative=("review_score", lambda x: (x <= 2).mean() * 100)).reset_index())


def payment_mix(orders: pd.DataFrame) -> pd.DataFrame:
    v = _valid(orders)
    return (v.groupby("payment_type").agg(orders=("order_id", "count"), revenue=("payment_value", "sum"),
                                          avg_installments=("installments", "mean"))
            .sort_values("orders", ascending=False).reset_index())

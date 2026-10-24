"""Fallback analyses so EVERY dashboard tab shows an answer, even when the uploaded file lacks a column.

Customer-level tabs (RFM, Cohorts/CLV, Churn) fall back to segment-level analysis on the best category column;
Reviews falls back to performance ratings; What-if always offers a revenue simulator.
All functions take the star-schema `fact_order_items` / `fact_orders` tables.
"""
import numpy as np
import pandas as pd

EXCLUDE = ("canceled", "unavailable")


def _valid(items: pd.DataFrame) -> pd.DataFrame:
    return items[~items["order_status"].isin(EXCLUDE)].copy()


def group_col(items: pd.DataFrame) -> str:
    """Pick the most informative grouping column available (category > region > seller)."""
    for c in ("category", "customer_state", "seller_id"):
        if c in items and 1 < items[c].nunique() <= 5000:
            return c
    return "category"


def segment_analysis(items: pd.DataFrame, col: str) -> pd.DataFrame:
    v = _valid(items)
    g = v.groupby(col).agg(revenue=("price", "sum"), orders=("order_id", "nunique"), units=("order_item_id", "count"),
                           profit=("est_gross_profit", "sum")).sort_values("revenue", ascending=False)
    g["aov"] = g["revenue"] / g["orders"]
    g["revenue_share_pct"] = g["revenue"] / g["revenue"].sum() * 100
    g["cumulative_pct"] = g["revenue_share_pct"].cumsum()
    g["segment"] = pd.cut(g["cumulative_pct"], [0, 80, 95, 100.001], labels=["A - Core (top 80%)",
                                                                             "B - Growth", "C - Long tail"])
    return g.reset_index()


def month_heatmap(items: pd.DataFrame, col: str, top: int = 15) -> pd.DataFrame:
    v = _valid(items)
    v["month"] = pd.to_datetime(v["purchase_date"]).dt.to_period("M").astype(str)
    keep = v.groupby(col)["price"].sum().nlargest(top).index
    return v[v[col].isin(keep)].pivot_table(index=col, columns="month", values="price", aggfunc="sum").fillna(0)


def declining_segments(items: pd.DataFrame, col: str, months: int = 3) -> pd.DataFrame:
    """'Churn' at segment level: revenue in the last N months vs the N months before."""
    v = _valid(items)
    v["purchase_date"] = pd.to_datetime(v["purchase_date"])
    end = v["purchase_date"].max()
    recent = v[v["purchase_date"] > end - pd.DateOffset(months=months)]
    prev = v[(v["purchase_date"] <= end - pd.DateOffset(months=months)) &
             (v["purchase_date"] > end - pd.DateOffset(months=2 * months))]
    out = pd.DataFrame({"previous": prev.groupby(col)["price"].sum(), "recent": recent.groupby(col)["price"].sum()})
    out = out.fillna(0)
    out = out[out["previous"] > 0]
    out["change_pct"] = (out["recent"] / out["previous"] - 1) * 100
    out["risk"] = np.select([out["change_pct"] <= -30, out["change_pct"] < 0], ["High", "Medium"], "Low / growing")
    return out.sort_values("change_pct").reset_index()


def performance_ratings(items: pd.DataFrame, col: str) -> pd.DataFrame:
    """1-5 star 'performance rating' per segment from revenue, growth and profit margin percentiles."""
    seg = segment_analysis(items, col)
    dec = declining_segments(items, col).set_index(col)["change_pct"]
    seg["growth_pct"] = seg[col].map(dec)
    seg["margin_pct"] = seg["profit"] / seg["revenue"].replace(0, np.nan) * 100
    parts = [seg["revenue"].rank(pct=True), seg["growth_pct"].rank(pct=True).fillna(.5),
             seg["margin_pct"].rank(pct=True).fillna(.5)]
    score = (0.5 * parts[0] + 0.3 * parts[1] + 0.2 * parts[2])
    seg["stars"] = (1 + score * 4).round(1)
    return seg.sort_values("stars", ascending=False)


def revenue_simulator(kpis: dict, orders_change_pct: float, aov_change_pct: float, margin_change_pp: float,
                      margin_pct: float) -> dict:
    rev, orders, aov = kpis.get("revenue", 0), kpis.get("orders", 0), kpis.get("aov", 0)
    new_orders = orders * (1 + orders_change_pct / 100)
    new_aov = aov * (1 + aov_change_pct / 100)
    new_rev = new_orders * new_aov
    new_margin = max(margin_pct + margin_change_pp, -100)
    return {"revenue": (rev, new_rev), "orders": (orders, new_orders), "aov": (aov, new_aov),
            "profit": (rev * margin_pct / 100, new_rev * new_margin / 100)}

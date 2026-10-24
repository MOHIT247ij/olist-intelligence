"""Customer segmentation: RFM scoring + rule-based segments + KMeans clusters.

Olist note: ~97% of customers order once, so Frequency has almost no spread.
We therefore rank F with Monetary as tie-breaker and also offer KMeans on log-scaled R/M.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

SEGMENT_ACTIONS = {
    "Champions": "Reward, early access, referral program",
    "Loyal": "Upsell higher-value categories, loyalty points",
    "Potential Loyalist": "2nd-purchase coupon within 30 days",
    "New Customers": "Onboarding journey, cross-sell top categories",
    "Big Spenders (one-time)": "Personalised premium recommendations",
    "At Risk": "Win-back campaign with time-bound discount",
    "Hibernating": "Low-cost reactivation email; suppress if no response",
    "Need Attention": "Survey + targeted offer",
}


def compute_rfm(orders: pd.DataFrame, ref_date=None) -> pd.DataFrame:
    d = orders[orders["order_status"] == "delivered"]
    ref = pd.Timestamp(ref_date) if ref_date else d["purchase_date"].max() + pd.Timedelta(days=1)
    rfm = d.groupby("customer_unique_id").agg(last_purchase=("purchase_date", "max"),
                                              frequency=("order_id", "nunique"),
                                              monetary=("payment_value", "sum"),
                                              state=("customer_state", "first"))
    rfm["recency_days"] = (ref - rfm["last_purchase"]).dt.days
    # quintile scores (rank first to avoid duplicate bin edges)
    rfm["r_score"] = pd.qcut(rfm["recency_days"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    rfm["f_score"] = pd.qcut((rfm["frequency"] + rfm["monetary"] / 1e7).rank(method="first"), 5,
                             labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["m_score"] = pd.qcut(rfm["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["rfm_score"] = rfm["r_score"].astype(str) + rfm["f_score"].astype(str) + rfm["m_score"].astype(str)
    rfm["segment"] = _segment_vectorized(rfm)
    rfm["recommended_action"] = rfm["segment"].map(SEGMENT_ACTIONS)
    return rfm.reset_index()


def _segment_vectorized(df: pd.DataFrame) -> np.ndarray:
    """Fast rule-based segments (same rules as _segment, no row-by-row apply)."""
    f, r, m = df["frequency"], df["r_score"], df["m_score"]
    rep = f >= 2
    conds = [rep & (r >= 4), rep & (r >= 3), rep,
             (r >= 4) & (m >= 4), r >= 4, m == 5, (r <= 2) & (m >= 3), r <= 2]
    labels = ["Champions", "Loyal", "At Risk", "Potential Loyalist", "New Customers",
              "Big Spenders (one-time)", "At Risk", "Hibernating"]
    return np.select(conds, labels, default="Need Attention")


def _segment(r) -> str:
    if r.frequency >= 2 and r.r_score >= 4:
        return "Champions"
    if r.frequency >= 2:
        return "Loyal" if r.r_score >= 3 else "At Risk"
    # single-purchase customers (the Olist majority)
    if r.r_score >= 4 and r.m_score >= 4:
        return "Potential Loyalist"
    if r.r_score >= 4:
        return "New Customers"
    if r.m_score == 5:
        return "Big Spenders (one-time)"
    if r.r_score <= 2 and r.m_score >= 3:
        return "At Risk"
    if r.r_score <= 2:
        return "Hibernating"
    return "Need Attention"


def segment_summary(rfm: pd.DataFrame) -> pd.DataFrame:
    s = rfm.groupby("segment").agg(customers=("customer_unique_id", "count"), revenue=("monetary", "sum"),
                                   avg_recency=("recency_days", "mean"), avg_frequency=("frequency", "mean"),
                                   avg_monetary=("monetary", "mean"))
    s["customer_share_pct"] = s["customers"] / s["customers"].sum() * 100
    s["revenue_share_pct"] = s["revenue"] / s["revenue"].sum() * 100
    s["recommended_action"] = s.index.map(SEGMENT_ACTIONS)
    return s.sort_values("revenue", ascending=False).reset_index()


def kmeans_clusters(rfm: pd.DataFrame, k: int = 4, seed: int = 42) -> pd.DataFrame:
    X = np.column_stack([np.log1p(rfm["recency_days"]), np.log1p(rfm["frequency"]), np.log1p(rfm["monetary"])])
    Xs = StandardScaler().fit_transform(X)
    out = rfm.copy()
    out["cluster"] = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(Xs)
    return out

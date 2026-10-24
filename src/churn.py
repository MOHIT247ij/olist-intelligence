"""Churn prediction with a leakage-free, time-based design.

Definition
  cutoff  = last date in data - CHURN_WINDOW_DAYS
  features: computed ONLY from orders on/before cutoff
  label   : churned = 1 if the customer places NO order in (cutoff, cutoff + window]

Olist reality: most customers never come back, so churn rate is very high (~95%+).
The useful business output is the RANKING: who is MOST likely to return (lowest churn
probability) and which high-value customers are slipping. Metrics: ROC-AUC, PR-AUC, lift.
"""
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src import config

NUM = ["recency_days", "frequency", "monetary", "avg_order_value", "tenure_days", "avg_review", "last_review",
       "late_rate", "avg_delivery_days", "avg_delay_days", "freight_share", "avg_installments", "n_categories",
       "avg_items"]
CAT = ["state", "main_payment"]


def build_features(orders: pd.DataFrame, items: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    o = orders[(orders["order_status"] == "delivered") & (orders["purchase_date"] <= as_of)].copy()
    o["freight_share"] = o["freight_value"] / o["gmv"].replace(0, np.nan)
    o = o.sort_values("purchase_date")
    g = o.groupby("customer_unique_id")
    f = g.agg(last_purchase=("purchase_date", "max"), first_purchase=("purchase_date", "min"),
              frequency=("order_id", "nunique"), monetary=("payment_value", "sum"),
              avg_review=("review_score", "mean"), last_review=("review_score", "last"),
              late_rate=("is_late", lambda x: x.astype(float).mean()), avg_delivery_days=("delivery_days", "mean"),
              avg_delay_days=("delay_days", "mean"), freight_share=("freight_share", "mean"),
              avg_installments=("installments", "mean"), avg_items=("items_count", "mean"),
              state=("customer_state", "last"), main_payment=("payment_type", lambda x: x.mode().iat[0]
                                                               if x.notna().any() else "unknown"))
    f["recency_days"] = (as_of - f["last_purchase"]).dt.days
    f["tenure_days"] = (f["last_purchase"] - f["first_purchase"]).dt.days
    f["avg_order_value"] = f["monetary"] / f["frequency"]
    cats = (items[items["order_id"].isin(o["order_id"])].groupby("customer_unique_id")["category"].nunique())
    f["n_categories"] = cats.reindex(f.index).fillna(0)
    top_states = o["customer_state"].value_counts().head(10).index
    f["state"] = f["state"].where(f["state"].isin(top_states), "OTHER")
    return f.drop(columns=["last_purchase", "first_purchase"])


def build_training_set(orders, items, window_days=config.CHURN_WINDOW_DAYS):
    max_date = orders["purchase_date"].max()
    cutoff = max_date - pd.Timedelta(days=window_days)
    X = build_features(orders, items, cutoff)
    future = orders[(orders["purchase_date"] > cutoff) & (orders["purchase_date"] <= max_date)
                    & ~orders["order_status"].isin(["canceled", "unavailable"])]
    y = (~X.index.isin(future["customer_unique_id"])).astype(int)
    return X, pd.Series(y, index=X.index, name="churned"), cutoff


def _pipeline(model):
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("sc", StandardScaler())]), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT)])
    return Pipeline([("pre", pre), ("model", model)])


def top_decile_lift(y_true, score) -> float:
    """Lift of the 10% customers with the highest RETURN probability (1 - churn prob)."""
    df = pd.DataFrame({"ret": 1 - np.asarray(y_true), "s": 1 - np.asarray(score)}).sort_values("s", ascending=False)
    top = df.head(max(len(df) // 10, 1))
    base = df["ret"].mean()
    return float(top["ret"].mean() / base) if base > 0 else float("nan")


def train(orders, items, seed: int = 42) -> dict:
    X, y, cutoff = build_training_set(orders, items)
    if y.nunique() < 2:
        raise ValueError("Only one class in label -- not enough repeat purchases in the data window.")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=seed)
    models = {
        "logistic_regression": _pipeline(LogisticRegression(max_iter=2000, class_weight="balanced")),
        "gradient_boosting": _pipeline(HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                                                      class_weight="balanced", random_state=seed)),
    }
    results = {}
    for name, m in models.items():
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        results[name] = {"roc_auc": roc_auc_score(yte, p), "pr_auc_return": average_precision_score(1 - yte, 1 - p),
                         "top_decile_lift": top_decile_lift(yte, p)}
    best = max(results, key=lambda k: results[k]["roc_auc"])
    model = models[best]
    sample = Xte.sample(min(len(Xte), 3000), random_state=seed)
    pi = permutation_importance(model, sample, yte.loc[sample.index], scoring="roc_auc", n_repeats=5,
                                random_state=seed)
    importance = (pd.DataFrame({"feature": NUM + CAT, "importance": pi.importances_mean})
                  .sort_values("importance", ascending=False))
    joblib.dump(model, config.MODELS_DIR / "churn_model.joblib")
    return {"cutoff": str(cutoff.date()), "n_customers": len(X), "churn_rate": float(y.mean()),
            "metrics": results, "best_model": best, "feature_importance": importance, "model": model}


def score_customers(model, orders, items, rfm: pd.DataFrame | None = None) -> pd.DataFrame:
    """Score every customer as of the latest date. Adds risk tier + value-at-risk."""
    as_of = orders["purchase_date"].max()
    X = build_features(orders, items, as_of)
    out = X[["recency_days", "frequency", "monetary", "avg_review", "state"]].copy()
    out["churn_probability"] = model.predict_proba(X)[:, 1]
    out["return_probability"] = 1 - out["churn_probability"]
    out["risk_tier"] = pd.qcut(out["churn_probability"].rank(method="first"), 3, labels=["Low", "Medium", "High"])
    out["value_at_risk"] = out["monetary"] * out["churn_probability"]
    if rfm is not None:
        out = out.join(rfm.set_index("customer_unique_id")[["segment"]], how="left")
    return out.reset_index().sort_values("value_at_risk", ascending=False)

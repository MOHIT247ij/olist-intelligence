"""Universal mode: turn ANY uploaded sales/transaction file into the same star schema as Olist,
then run EVERY analysis (KPIs, RFM, churn, forecast, cohorts, CLV, basket, sellers, sentiment, what-if, AI).

Each uploaded dataset gets its own workspace:  data/workspaces/<name>/{processed, reports, olist.db}
so the original Olist dashboard is never overwritten.
"""
import json
import re
import shutil

import numpy as np
import pandas as pd

from src import config

WORKSPACES = config.ROOT / "data" / "workspaces"

# role -> (required?, keywords in column name, preferred column role from auto_analyzer)
ROLES = {
    "date": ("Order / transaction date", ["order_date", "purchase", "invoice_date", "transaction_date", "date",
                                          "timestamp", "time", "created", "day"]),
    "amount": ("Sales amount (revenue)", ["revenue", "sales", "amount", "total", "price", "value", "payment", "gmv",
                                          "net", "turnover", "income"]),
    "customer": ("Customer ID", ["customer_id", "customer", "client", "user", "buyer", "member", "account",
                                 "cust", "shopper", "email"]),
    "order": ("Order / invoice ID", ["order_id", "invoice", "order", "transaction", "receipt", "bill", "txn"]),
    "product": ("Product / category", ["category", "product_category", "sub_category", "product_line", "product",
                                       "item", "sku", "description", "segment", "type"]),
    "region": ("Region / state / city", ["state", "region", "city", "country", "province", "location", "zone",
                                         "territory", "market"]),
    "quantity": ("Quantity", ["quantity", "qty", "units", "count"]),
    "profit": ("Profit", ["profit", "margin", "gross_profit"]),
    "rating": ("Rating / review score", ["rating", "review_score", "stars", "score", "satisfaction", "nps"]),
    "review_text": ("Review / comment text", ["review", "comment", "feedback", "text", "remarks", "message"]),
    "seller": ("Seller / store / salesperson", ["seller", "vendor", "supplier", "salesperson", "sales_rep",
                                                "agent", "merchant", "store", "shop", "branch", "outlet"]),
    "payment": ("Payment method", ["payment_type", "payment_method", "payment_mode", "pay", "method", "channel"]),
    "status": ("Order status", ["status", "order_status", "state_of_order"]),
    "delivery_date": ("Delivery date", ["delivered", "delivery_date", "ship_date", "shipped", "arrival"]),
    "promised_date": ("Promised / estimated date", ["estimated", "promised", "expected", "due_date", "eta"]),
    "shipping": ("Shipping cost", ["shipping", "freight", "delivery_fee", "ship_cost"]),
}
TYPE_OK = {"date": ("date",), "delivery_date": ("date",), "promised_date": ("date",),
           "amount": ("numeric",), "quantity": ("numeric", "category"), "profit": ("numeric",),
           "rating": ("numeric", "category"), "shipping": ("numeric",),
           "review_text": ("text", "category"), "customer": ("id", "category", "numeric", "text"),
           "order": ("id", "category", "numeric"), "seller": ("id", "category", "numeric"),
           "product": ("category", "id", "text"), "region": ("category",), "payment": ("category",),
           "status": ("category",)}


def detect_mapping(df: pd.DataFrame, prof: pd.DataFrame) -> dict:
    role_of = dict(zip(prof["column"], prof["role"]))
    used, mapping = set(), {}
    for role, (_, keys) in ROLES.items():
        best, best_score = None, 0
        for c in df.columns:
            if c in used or role_of.get(c) not in TYPE_OK[role]:
                continue
            for rank, k in enumerate(keys):
                if k in c:
                    score = 100 - rank * 3 + (20 if c == k or c.startswith(k) else 0)
                    if role in ("customer", "order", "seller") and (c.endswith("_id") or c.endswith("id")):
                        score += 15
                    if score > best_score:
                        best, best_score = c, score
                    break
        if best:
            mapping[role] = best
            used.add(best)
    # fallbacks: first date column / main numeric column
    if "date" not in mapping:
        dates = [c for c in df.columns if role_of.get(c) == "date" and c not in used]
        if dates:
            mapping["date"] = dates[0]
    if "amount" not in mapping:
        nums = [c for c in df.columns if role_of.get(c) == "numeric" and c not in used]
        if nums:
            mapping["amount"] = max(nums, key=lambda c: df[c].sum())
    return mapping


def fill_substitutes(df: pd.DataFrame, prof: pd.DataFrame, m: dict) -> tuple[dict, dict]:
    """If Product / Region / Seller columns are missing, reuse other category columns so those dashboards still work."""
    m = dict(m)
    role_of = dict(zip(prof["column"], prof["role"]))
    used = set(m.values())
    cats = [c for c in df.columns if role_of.get(c) in ("category", "id") and c not in used
            and 2 <= df[c].nunique() <= 2000]
    cats.sort(key=lambda c: df[c].nunique())          # fewest groups first
    subs = {}
    prefs = {"region": lambda n: n <= 100, "product": lambda n: n >= 3, "seller": lambda n: 3 <= n <= 2000}
    for role in ("product", "region", "seller"):
        if role in m:
            continue
        pick = next((c for c in cats if prefs[role](df[c].nunique()) and c not in subs.values()), None)
        if pick is None and role == "product" and cats:
            pick = cats[-1]
        if pick:
            m[role] = pick
            subs[role] = pick
    return m, subs


def capabilities(m: dict) -> dict:
    has = lambda *r: all(x in m for x in r)  # noqa: E731
    return {"Revenue & trends": has("date", "amount"), "Forecast & anomaly alerts": has("date", "amount"),
            "RFM / Cohorts / CLV / Churn": has("date", "amount", "customer"),
            "Products & Pareto": has("product"), "Market basket": has("product") and has("order"),
            "Geography": has("region"), "Seller scorecard": has("seller"),
            "Reviews & sentiment": has("rating") or has("review_text"),
            "Delivery & what-if": has("delivery_date", "promised_date") and has("rating")}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "dataset"


# ---------------------------------------------------------------- star schema
def build_star(df: pd.DataFrame, m: dict) -> dict[str, pd.DataFrame]:
    if "date" not in m or "amount" not in m:
        raise ValueError("Need at least a DATE column and an AMOUNT (sales) column.")
    d = df.copy()
    d["_date"] = pd.to_datetime(d[m["date"]], errors="coerce")
    d = d.dropna(subset=["_date"])
    amt = pd.to_numeric(d[m["amount"]], errors="coerce").fillna(0)
    d["_price"] = amt
    d["_customer"] = d[m["customer"]].astype(str) if "customer" in m else ("ROW" + d.index.astype(str))
    d["_order"] = d[m["order"]].astype(str) if "order" in m else ("ORD" + d.index.astype(str))
    d["_product"] = d[m["product"]].astype(str).fillna("unknown") if "product" in m else "all_products"
    d["_category"] = d["_product"]
    d["_region"] = d[m["region"]].astype(str).fillna("unknown") if "region" in m else "all"
    d["_seller"] = d[m["seller"]].astype(str) if "seller" in m else "all_sellers"
    d["_freight"] = pd.to_numeric(d[m["shipping"]], errors="coerce").fillna(0) if "shipping" in m else 0.0
    d["_profit"] = pd.to_numeric(d[m["profit"]], errors="coerce") if "profit" in m else np.nan
    d["_status"] = d[m["status"]].astype(str).str.lower() if "status" in m else "delivered"
    st = d["_status"]
    d["_status"] = np.where(st.str.contains("cancel|return|refund|fail|void", regex=True), "canceled",
                            np.where(st.str.contains("pending|process|ship|transit", regex=True), "shipped",
                                     "delivered"))
    d["_rating"] = pd.to_numeric(d[m["rating"]], errors="coerce") if "rating" in m else np.nan
    if "rating" in m and d["_rating"].max() > 5:          # rescale 1-10 / 0-100 scales to 1-5
        mx = d["_rating"].max()
        d["_rating"] = 1 + (d["_rating"] / mx) * 4
    d["_delivered"] = pd.to_datetime(d[m["delivery_date"]], errors="coerce") if "delivery_date" in m else pd.NaT
    d["_promised"] = pd.to_datetime(d[m["promised_date"]], errors="coerce") if "promised_date" in m else pd.NaT
    d["_payment"] = d[m["payment"]].astype(str) if "payment" in m else "unknown"

    d["purchase_date"] = d["_date"].dt.normalize()
    d["date_key"] = d["purchase_date"].dt.strftime("%Y%m%d").astype(int)
    d["order_item_id"] = d.groupby("_order").cumcount() + 1
    d["product_id"] = d["_product"]

    margin = config.ASSUMED_GROSS_MARGIN
    items = pd.DataFrame({
        "order_id": d["_order"], "order_item_id": d["order_item_id"], "product_id": d["product_id"],
        "seller_id": d["_seller"], "price": d["_price"], "freight_value": d["_freight"],
        "customer_unique_id": d["_customer"], "customer_state": d["_region"], "purchase_date": d["purchase_date"],
        "date_key": d["date_key"], "order_status": d["_status"], "category": d["_category"]})
    items["est_gross_profit"] = d["_profit"].where(d["_profit"].notna(), items["price"] * margin)
    items["est_cogs"] = items["price"] - items["est_gross_profit"]

    g = d.groupby("_order")
    o = g.agg(customer_unique_id=("_customer", "first"), order_status=("_status", "first"),
              order_purchase_timestamp=("_date", "min"), purchase_date=("purchase_date", "min"),
              date_key=("date_key", "min"), order_delivered_customer_date=("_delivered", "max"),
              order_estimated_delivery_date=("_promised", "max"), items_count=("order_item_id", "count"),
              sellers_count=("_seller", "nunique"), product_revenue=("_price", "sum"),
              freight_value=("_freight", "sum"), payment_type=("_payment", "first"),
              review_score=("_rating", "mean"), customer_state=("_region", "first")).reset_index()
    o = o.rename(columns={"_order": "order_id"})
    o["customer_id"] = o["customer_unique_id"]
    o["gmv"] = o["product_revenue"] + o["freight_value"]
    o["payment_value"] = o["gmv"]
    o["installments"] = 1
    o["has_comment"] = 0
    prof_sum = items.groupby("order_id")["est_gross_profit"].sum()
    o["est_gross_profit"] = o["order_id"].map(prof_sum)
    ts, dl, pr = o["order_purchase_timestamp"], o["order_delivered_customer_date"], o["order_estimated_delivery_date"]
    o["delivery_days"] = (dl - ts).dt.total_seconds() / 86400
    o["estimated_days"] = (pr - ts).dt.total_seconds() / 86400
    o["delay_days"] = (dl - pr).dt.total_seconds() / 86400
    o["is_late"] = (o["delay_days"] > 0).astype("float").where(o["delay_days"].notna())
    o["is_delivered"] = (o["order_status"] == "delivered").astype(int)

    dim_customer = (o.sort_values("order_purchase_timestamp").groupby("customer_unique_id")
                    .agg(state=("customer_state", "first"), first_order_ts=("order_purchase_timestamp", "min"),
                         last_order_ts=("order_purchase_timestamp", "max")).reset_index())
    dim_customer["city"] = dim_customer["state"]
    dim_product = items.groupby("product_id").agg(category=("category", "first")).reset_index()
    dim_product["category_pt"] = dim_product["category"]
    dim_seller = items.groupby("seller_id").agg(state=("customer_state", lambda x: x.mode().iat[0])).reset_index()
    dim_seller["city"] = dim_seller["state"]
    dates = pd.date_range(o["purchase_date"].min(), o["purchase_date"].max(), freq="D")
    dim_date = pd.DataFrame({"date": dates})
    dim_date["date_key"] = dim_date["date"].dt.strftime("%Y%m%d").astype(int)
    dim_date["year"], dim_date["quarter"] = dim_date["date"].dt.year, dim_date["date"].dt.quarter
    dim_date["month"], dim_date["month_name"] = dim_date["date"].dt.month, dim_date["date"].dt.strftime("%b")
    dim_date["year_month"] = dim_date["date"].dt.strftime("%Y-%m")
    dim_date["week_of_year"] = dim_date["date"].dt.isocalendar().week.astype(int)
    dim_date["day_name"] = dim_date["date"].dt.day_name()
    dim_date["is_weekend"] = (dim_date["date"].dt.dayofweek >= 5).astype(int)

    reviews = None
    if "rating" in m or "review_text" in m:
        txt = d[m["review_text"]].astype(str).where(d[m["review_text"]].notna(), None) if "review_text" in m else None
        rv = pd.DataFrame({"order_id": d["_order"], "review_score": d["_rating"].fillna(3),
                           "review_comment_title": None, "review_comment_message": txt,
                           "review_creation_date": d["_date"], "review_answer_timestamp": d["_date"]})
        rv["review_id"] = "R" + rv.index.astype(str)
        reviews = rv.drop_duplicates("order_id")
    return {"fact_orders": o, "fact_order_items": items, "dim_customer": dim_customer, "dim_product": dim_product,
            "dim_seller": dim_seller, "dim_date": dim_date, "_reviews": reviews}


# ---------------------------------------------------------------- workspaces
def workspace_dirs(name: str):
    base = WORKSPACES / slug(name)
    return base, base / "processed", base / "reports", base / "olist.db"


def list_workspaces() -> list[dict]:
    out = []
    if WORKSPACES.exists():
        for p in sorted(WORKSPACES.iterdir()):
            meta = p / "reports" / "summary.json"
            if meta.exists():
                try:
                    out.append({"slug": p.name, **json.loads(meta.read_text()).get("meta", {})})
                except Exception:
                    pass
    return out


def delete_workspace(slug_name: str) -> None:
    shutil.rmtree(WORKSPACES / slug_name, ignore_errors=True)


def run_workspace(df: pd.DataFrame, mapping: dict, name: str, currency: str = "₹", source_file: str = "") -> dict:
    """Build star schema for the upload and run ALL analytics into its own workspace."""
    import sqlite3

    import pipeline
    base, proc, rep, dbp = workspace_dirs(name)
    if base.exists():
        shutil.rmtree(base)
    proc.mkdir(parents=True)
    rep.mkdir(parents=True)
    from src.auto_analyzer import profile
    mapping, subs = fill_substitutes(df, profile(df), mapping)
    tables = build_star(df, mapping)
    reviews = tables.pop("_reviews")
    con = sqlite3.connect(dbp)
    try:
        for t, frame in tables.items():
            frame.to_csv(proc / f"{t}.csv", index=False)
            out = frame.copy()
            for c in out.columns:
                if pd.api.types.is_datetime64_any_dtype(out[c]):
                    out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S")
            out.to_sql(t, con, if_exists="replace", index=False, chunksize=20_000)
    finally:
        con.close()
    orders = pd.read_csv(proc / "fact_orders.csv", parse_dates=["order_purchase_timestamp", "purchase_date",
                                                                  "order_delivered_customer_date",
                                                                  "order_estimated_delivery_date"])
    items = pd.read_csv(proc / "fact_order_items.csv", parse_dates=["purchase_date"])
    meta = {"dataset": name, "slug": slug(name), "currency": currency, "source_file": source_file,
            "rows": int(len(df)), "mapping": mapping, "substitutes": subs, "capabilities": capabilities(mapping)}
    return pipeline.run_analytics(orders, items, tables["dim_seller"], reviews, proc, rep, meta)

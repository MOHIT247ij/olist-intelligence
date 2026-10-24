"""ETL: raw Olist CSVs -> cleaned star schema -> CSV (data/processed) + database.

Star schema
  dim_customer, dim_product, dim_seller, dim_date
  fact_orders       (1 row per order)
  fact_order_items  (1 row per order line)

Run:  python -m src.etl
"""
import json
import logging

import pandas as pd

from src import config, db

log = logging.getLogger("etl")

DATE_COLS = {
    "orders": ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
               "order_delivered_customer_date", "order_estimated_delivery_date"],
    "order_items": ["shipping_limit_date"],
    "reviews": ["review_creation_date", "review_answer_timestamp"],
}


# ---------------------------------------------------------------- Extract
def extract() -> dict[str, pd.DataFrame]:
    missing = [f for f in config.RAW_FILES.values() if not (config.RAW_DIR / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing in data/raw: {missing}. Run scripts/download_data.py "
                                f"(or scripts/generate_sample_data.py for a test run).")
    raw = {}
    for key, fname in config.RAW_FILES.items():
        raw[key] = pd.read_csv(config.RAW_DIR / fname, parse_dates=DATE_COLS.get(key, []))
        log.info("extract %-22s %8d rows", key, len(raw[key]))
    return raw


# ---------------------------------------------------------------- Transform
def data_quality(raw: dict) -> dict:
    return {k: {"rows": int(len(v)), "duplicates": int(v.duplicated().sum()),
                "nulls": {c: int(n) for c, n in v.isna().sum().items() if n}} for k, v in raw.items()}


def transform(raw: dict) -> dict[str, pd.DataFrame]:
    r = {k: v.drop_duplicates().copy() for k, v in raw.items()}

    # geolocation: many rows per zip -> one median point per zip prefix
    geo = (r["geolocation"].groupby("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]]
           .median().rename(columns={"geolocation_lat": "lat", "geolocation_lng": "lng"}))

    # ---- dim_product
    p = r["products"].merge(r["category_translation"], on="product_category_name", how="left")
    p["product_category_name"] = p["product_category_name"].fillna("unknown")
    p["category"] = p["product_category_name_english"].fillna(p["product_category_name"])
    p["volume_cm3"] = p["product_length_cm"] * p["product_height_cm"] * p["product_width_cm"]
    dim_product = p[["product_id", "category", "product_category_name", "product_photos_qty",
                     "product_weight_g", "volume_cm3"]].rename(columns={"product_category_name": "category_pt"})

    # ---- dim_seller
    s = r["sellers"].merge(geo, left_on="seller_zip_code_prefix", right_index=True, how="left")
    dim_seller = s.rename(columns={"seller_zip_code_prefix": "zip_prefix", "seller_city": "city",
                                   "seller_state": "state"})

    # ---- orders base
    o = r["orders"].merge(r["customers"], on="customer_id", how="left")
    o["purchase_date"] = o["order_purchase_timestamp"].dt.normalize()
    o["date_key"] = o["purchase_date"].dt.strftime("%Y%m%d").astype(int)
    o["delivery_days"] = (o["order_delivered_customer_date"] - o["order_purchase_timestamp"]).dt.total_seconds() / 86400
    o["estimated_days"] = (o["order_estimated_delivery_date"] - o["order_purchase_timestamp"]).dt.total_seconds() / 86400
    o["delay_days"] = (o["order_delivered_customer_date"] - o["order_estimated_delivery_date"]).dt.total_seconds() / 86400
    o["is_late"] = (o["delay_days"] > 0).astype("Int64").where(o["delivery_days"].notna())
    o["is_delivered"] = (o["order_status"] == "delivered").astype(int)

    # items aggregate per order
    it = r["order_items"]
    agg_it = it.groupby("order_id").agg(items_count=("order_item_id", "count"), product_revenue=("price", "sum"),
                                        freight_value=("freight_value", "sum"), sellers_count=("seller_id", "nunique"))
    # payments per order (main type = largest payment)
    pay = r["payments"]
    main_pay = pay.sort_values("payment_value", ascending=False).drop_duplicates("order_id")
    agg_pay = pay.groupby("order_id").agg(payment_value=("payment_value", "sum"),
                                          installments=("payment_installments", "max"))
    agg_pay["payment_type"] = main_pay.set_index("order_id")["payment_type"]
    # reviews: keep latest review per order
    rev = (r["reviews"].sort_values("review_answer_timestamp").drop_duplicates("order_id", keep="last")
           .set_index("order_id")[["review_score", "review_comment_message"]])
    rev["has_comment"] = rev["review_comment_message"].notna().astype(int)

    fo = (o.join(agg_it, on="order_id").join(agg_pay, on="order_id").join(rev.drop(columns="review_comment_message"),
                                                                         on="order_id"))
    for c in ("items_count", "product_revenue", "freight_value", "payment_value"):
        fo[c] = fo[c].fillna(0)
    fo["gmv"] = fo["product_revenue"] + fo["freight_value"]
    fo["est_gross_profit"] = fo["product_revenue"] * config.ASSUMED_GROSS_MARGIN
    fact_orders = fo[["order_id", "customer_id", "customer_unique_id", "order_status", "order_purchase_timestamp",
                      "purchase_date", "date_key", "order_delivered_customer_date", "order_estimated_delivery_date",
                      "delivery_days", "estimated_days", "delay_days", "is_late", "is_delivered", "items_count",
                      "sellers_count", "product_revenue", "freight_value", "gmv", "payment_value", "payment_type",
                      "installments", "review_score", "has_comment", "est_gross_profit", "customer_state"]]

    # ---- fact_order_items
    foi = it.merge(o[["order_id", "customer_unique_id", "customer_state", "purchase_date", "date_key",
                      "order_status"]], on="order_id", how="left")
    foi = foi.merge(dim_product[["product_id", "category"]], on="product_id", how="left")
    foi["est_cogs"] = foi["price"] * (1 - config.ASSUMED_GROSS_MARGIN)
    foi["est_gross_profit"] = foi["price"] - foi["est_cogs"]
    fact_order_items = foi.drop(columns=["shipping_limit_date"])

    # ---- dim_customer (one row per real person = customer_unique_id)
    c = (r["customers"].merge(o[["customer_id", "order_purchase_timestamp"]], on="customer_id", how="left")
         .sort_values("order_purchase_timestamp"))
    first = c.drop_duplicates("customer_unique_id", keep="first")
    last = c.drop_duplicates("customer_unique_id", keep="last").set_index("customer_unique_id")
    dim_customer = first[["customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"]].copy()
    dim_customer["first_order_ts"] = first["order_purchase_timestamp"].values
    dim_customer["last_order_ts"] = last.loc[dim_customer["customer_unique_id"], "order_purchase_timestamp"].values
    dim_customer = dim_customer.merge(geo, left_on="customer_zip_code_prefix", right_index=True, how="left")
    dim_customer = dim_customer.rename(columns={"customer_zip_code_prefix": "zip_prefix", "customer_city": "city",
                                                "customer_state": "state"})

    # ---- dim_date
    dates = pd.date_range(o["purchase_date"].min(), o["purchase_date"].max(), freq="D")
    dim_date = pd.DataFrame({"date": dates})
    dim_date["date_key"] = dim_date["date"].dt.strftime("%Y%m%d").astype(int)
    dim_date["year"] = dim_date["date"].dt.year
    dim_date["quarter"] = dim_date["date"].dt.quarter
    dim_date["month"] = dim_date["date"].dt.month
    dim_date["month_name"] = dim_date["date"].dt.strftime("%b")
    dim_date["year_month"] = dim_date["date"].dt.strftime("%Y-%m")
    dim_date["week_of_year"] = dim_date["date"].dt.isocalendar().week.astype(int)
    dim_date["day_name"] = dim_date["date"].dt.day_name()
    dim_date["is_weekend"] = (dim_date["date"].dt.dayofweek >= 5).astype(int)

    return {"dim_customer": dim_customer, "dim_product": dim_product, "dim_seller": dim_seller,
            "dim_date": dim_date, "fact_orders": fact_orders, "fact_order_items": fact_order_items}


# ---------------------------------------------------------------- Load
def load(tables: dict[str, pd.DataFrame], to_db: bool = True) -> None:
    for name, df in tables.items():
        df.to_csv(config.PROCESSED_DIR / f"{name}.csv", index=False)
    if to_db:
        con = db.get_connection()
        if db.dialect() == "postgresql":
            db.drop_tables_cascade(list(tables), con)
        for name, df in tables.items():
            out = df.copy()
            if db.dialect() == "sqlite":  # sqlite has no datetime type
                for col in out.select_dtypes(include=["datetime", "datetimetz"]).columns:
                    out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            db.write_table(out, name, con)
            log.info("load %-18s %8d rows -> %s", name, len(df), db.dialect())
        if db.dialect() == "postgresql":
            for f in ("01_constraints_indexes.sql", "02_analytics_views.sql"):
                db.execute_sql_file(config.SQL_DIR / f, con)
                log.info("applied %s", f)
        if hasattr(con, "close"):
            con.close()


def run(to_db: bool = True) -> dict[str, pd.DataFrame]:
    raw = extract()
    (config.REPORTS_DIR / "data_quality.json").write_text(json.dumps(data_quality(raw), indent=2))
    tables = transform(raw)
    load(tables, to_db=to_db)
    return tables


def read_processed(name: str) -> pd.DataFrame:
    df = pd.read_csv(config.PROCESSED_DIR / f"{name}.csv")
    for c in df.columns:
        if c.endswith(("_ts", "_timestamp", "_date")) or c in ("date",):
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()

"""Central configuration: paths, env vars, business assumptions."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file():
    """Read KEY=VALUE lines from .env (also accepts Windows' accidental .env.txt / env.txt). No extra package."""
    for name in (".env", ".env.txt", "env.txt"):
        f = ROOT / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if val and not os.getenv(key):
                os.environ[key] = val


def _load_streamlit_secrets():
    """Streamlit Cloud: values set in the app's Secrets panel become env vars."""
    try:
        import streamlit as st
        for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "DATABASE_URL"):
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass


_load_env_file()
_load_streamlit_secrets()

RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
SQL_DIR = ROOT / "sql"
SQLITE_PATH = ROOT / "data" / "olist.db"

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_URL_READONLY = os.getenv("DATABASE_URL_READONLY", "").strip() or DATABASE_URL

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ASSUMED_GROSS_MARGIN = float(os.getenv("ASSUMED_GROSS_MARGIN", "0.35"))
CHURN_WINDOW_DAYS = int(os.getenv("CHURN_WINDOW_DAYS", "180"))

# Kaggle dataset: Brazilian E-Commerce Public Dataset by Olist
KAGGLE_DATASET = "olistbr/brazilian-ecommerce"

RAW_FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

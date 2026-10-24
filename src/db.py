"""Database helper: PostgreSQL via SQLAlchemy if DATABASE_URL set, else local SQLite."""
import sqlite3
import pandas as pd

from src import config


def get_connection(readonly: bool = False):
    url = config.DATABASE_URL_READONLY if readonly else config.DATABASE_URL
    if url:
        from sqlalchemy import create_engine
        return create_engine(url, pool_pre_ping=True)
    return sqlite3.connect(config.SQLITE_PATH)


def ensure_sqlite() -> None:
    """If running without PostgreSQL and data/olist.db is missing (e.g. Streamlit Cloud), rebuild it
    from the star-schema CSVs in data/processed so the AI features can query it."""
    if config.DATABASE_URL or config.SQLITE_PATH.exists():
        return
    tables = ["dim_customer", "dim_product", "dim_seller", "dim_date", "fact_orders", "fact_order_items"]
    if not all((config.PROCESSED_DIR / f"{t}.csv").exists() for t in tables):
        return
    con = sqlite3.connect(config.SQLITE_PATH)
    try:
        for t in tables:
            pd.read_csv(config.PROCESSED_DIR / f"{t}.csv").to_sql(t, con, if_exists="replace", index=False,
                                                                  chunksize=20_000)
    finally:
        con.close()


def dialect() -> str:
    return "postgresql" if config.DATABASE_URL else "sqlite"


def write_table(df: pd.DataFrame, name: str, con=None) -> None:
    con = con or get_connection()
    df.to_sql(name, con, if_exists="replace", index=False,
              chunksize=10_000, method="multi" if dialect() == "postgresql" else None)


def execute_sql_file(path, con=None) -> None:
    """Execute a .sql file statement by statement (PostgreSQL only)."""
    from sqlalchemy import text
    engine = con or get_connection()
    sql = "\n".join(l for l in open(path, encoding="utf-8").read().splitlines() if not l.strip().startswith("--"))
    with engine.begin() as c:
        for stmt in (s.strip() for s in sql.split(";")):
            if stmt:
                c.execute(text(stmt))


def drop_tables_cascade(names, con=None) -> None:
    """PostgreSQL: drop tables (and dependent views) before a full reload."""
    from sqlalchemy import text
    engine = con or get_connection()
    with engine.begin() as c:
        for n in names:
            c.execute(text(f'DROP TABLE IF EXISTS "{n}" CASCADE'))


def query(sql: str, readonly: bool = True) -> pd.DataFrame:
    con = get_connection(readonly=readonly)
    try:
        return pd.read_sql(sql, con)
    finally:
        if isinstance(con, sqlite3.Connection):
            con.close()

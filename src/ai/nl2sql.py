"""Natural Language -> SQL with safety guardrails.

Flow: question -> Gemini (schema-aware prompt) -> SQL -> validate (SELECT-only, single
statement, no system tables, LIMIT enforced) -> run on READ-ONLY connection -> Gemini explains result.
"""
import re

import pandas as pd

from src import db
from src.ai.gemini_client import generate
from src.ai.fallback_queries import match_builtin, summarize

SCHEMA = """
fact_orders(order_id PK, customer_unique_id FK->dim_customer, order_status, order_purchase_timestamp,
  purchase_date, date_key FK->dim_date, delivery_days, estimated_days, delay_days (positive = late),
  is_late 0/1, is_delivered 0/1, items_count, sellers_count, product_revenue, freight_value,
  gmv (=product_revenue+freight), payment_value, payment_type, installments, review_score 1-5,
  has_comment, est_gross_profit, customer_state)
fact_order_items(order_id FK, order_item_id, product_id FK, seller_id FK, price, freight_value,
  customer_unique_id, customer_state, purchase_date, date_key, order_status, category, est_cogs, est_gross_profit)
dim_customer(customer_unique_id PK, zip_prefix, city, state, first_order_ts, last_order_ts, lat, lng)
dim_product(product_id PK, category (English), category_pt, product_photos_qty, product_weight_g, volume_cm3)
dim_seller(seller_id PK, zip_prefix, city, state, lat, lng)
dim_date(date_key PK, date, year, quarter, month, month_name, year_month 'YYYY-MM', week_of_year, day_name, is_weekend)
Business rules: revenue = SUM(product_revenue) excluding order_status IN ('canceled','unavailable').
Profit columns are ESTIMATES (assumed margin). customer_state holds the customer's region/state/city; category holds the product or category.
"""

SYSTEM = """You are a senior data analyst writing {dialect} SQL for an e-commerce star schema.
Rules:
- Return ONLY one SQL SELECT (or WITH ... SELECT) statement, no markdown, no explanation.
- Use only these tables/columns:
{schema}
- Always alias aggregates with readable snake_case names.
- Add ORDER BY for rankings and LIMIT {limit} unless the user asks for a single number.
- If the question cannot be answered from the schema, return exactly: SELECT 'UNANSWERABLE' AS error"""

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|merge|call|execute|"
                       r"pg_sleep|pg_read_file|lo_import|attach|pragma|vacuum)\b|pg_catalog|information_schema|sqlite_master",
                       re.IGNORECASE)


class UnsafeSQL(ValueError):
    pass


def clean_sql(text: str) -> str:
    text = re.sub(r"^```(?:sql)?|```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    return text.rstrip(";").strip()


def validate_sql(sql: str, limit: int = 500) -> str:
    s = clean_sql(sql)
    if ";" in s:
        raise UnsafeSQL("Multiple statements are not allowed.")
    if not re.match(r"^\s*(select|with)\b", s, re.IGNORECASE):
        raise UnsafeSQL("Only SELECT queries are allowed.")
    if FORBIDDEN.search(s):
        raise UnsafeSQL("Query contains a forbidden keyword.")
    if not re.search(r"\blimit\s+\d+\s*$", s, re.IGNORECASE):
        s = f"SELECT * FROM ({s}) AS q LIMIT {limit}"
    return s


def question_to_sql(question: str, limit: int = 100) -> str:
    system = SYSTEM.format(dialect=db.dialect(), schema=SCHEMA, limit=limit)
    return clean_sql(generate(question, system=system, temperature=0.0))


def explain(question: str, sql: str, df: pd.DataFrame) -> str:
    preview = df.head(30).to_csv(index=False)
    prompt = (f"Question: {question}\nSQL used:\n{sql}\nResult (first rows):\n{preview}\n\n"
              "In 3-5 bullet points: answer the question with the actual numbers, highlight one insight, "
              "and suggest one business action. Be concise. Do not invent numbers not in the result.")
    return generate(prompt, system="You are a concise e-commerce business analyst.")


def ask(question: str, explain_result: bool = True, max_retries: int = 1) -> dict:
    """Full NL->SQL loop with one self-correction retry on SQL error.
    If Gemini is busy/unreachable, falls back to built-in SQL for common business questions."""
    try:
        sql, err = question_to_sql(question), None
    except Exception as gem_err:
        builtin = match_builtin(question)
        if builtin is None:
            raise
        safe = validate_sql(builtin)
        df = db.query(safe, readonly=True)
        return {"question": question, "sql": safe, "error": None, "data": df, "mode": "builtin",
                "answer": summarize(question, df) + f"\n\n_Gemini unavailable ({str(gem_err)[:80]}...) -- "
                          "answered with a built-in query._"}
    for attempt in range(max_retries + 1):
        try:
            safe = validate_sql(sql)
            df = db.query(safe, readonly=True)
            break
        except UnsafeSQL:
            raise
        except Exception as e:  # SQL error -> ask Gemini to fix once
            err = str(e)
            if attempt == max_retries:
                return {"question": question, "sql": sql, "error": err, "data": None, "answer": None}
            sql = clean_sql(generate(f"This {db.dialect()} query failed.\nQuery:\n{sql}\nError:\n{err[:800]}\n"
                                     f"Schema:\n{SCHEMA}\nReturn ONLY the corrected SQL.", temperature=0.0))
    answer = None
    if explain_result:
        try:
            answer = explain(question, safe, df)
        except Exception:  # explanation is optional -- never lose the result because of it
            answer = summarize(question, df)
    return {"question": question, "sql": safe, "error": None, "data": df, "answer": answer, "mode": "gemini"}

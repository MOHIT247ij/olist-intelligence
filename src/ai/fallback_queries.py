"""Built-in SQL for common business questions (used when Gemini is busy).
Portable across SQLite and PostgreSQL (years filtered via integer date_key)."""
import re

import pandas as pd

VALID = "o.order_status NOT IN ('canceled', 'unavailable')"


def _year_filter(q: str, alias: str = "o") -> str:
    m = re.search(r"\b(2016|2017|2018)\b", q)
    return f" AND {alias}.date_key BETWEEN {m.group(1)}0101 AND {m.group(1)}1231" if m else ""


def _top_n(q: str, default: int = 10) -> int:
    m = re.search(r"\btop\s+(\d+)", q)
    return int(m.group(1)) if m else default


def match_builtin(question: str):
    q = question.lower()
    has = lambda *w: any(x in q for x in w)  # noqa: E731
    yf, n = _year_filter(q), _top_n(q)

    if has("state") and has("revenue", "sales"):
        return (f"SELECT o.customer_state AS state, ROUND(SUM(o.product_revenue), 2) AS revenue, "
                f"COUNT(*) AS orders FROM fact_orders o WHERE {VALID}{yf} "
                f"GROUP BY o.customer_state ORDER BY revenue DESC LIMIT {_top_n(q, 5)}")
    if has("categor", "product") and has("review", "rating"):
        order = "ASC" if has("worst", "lowest", "bad") else "DESC"
        return ("SELECT i.category, ROUND(AVG(o.review_score), 2) AS avg_review, COUNT(DISTINCT o.order_id) AS orders "
                "FROM fact_order_items i JOIN fact_orders o ON o.order_id = i.order_id "
                f"WHERE o.review_score IS NOT NULL{_year_filter(q)} GROUP BY i.category "
                f"HAVING COUNT(DISTINCT o.order_id) >= 30 ORDER BY avg_review {order} LIMIT {n}")
    if has("categor", "product") and has("revenue", "sales", "top", "best"):
        return ("SELECT i.category, ROUND(SUM(i.price), 2) AS revenue, COUNT(*) AS units "
                "FROM fact_order_items i JOIN fact_orders o ON o.order_id = i.order_id "
                f"WHERE {VALID}{yf} GROUP BY i.category ORDER BY revenue DESC LIMIT {n}")
    if has("month", "trend") :
        metric = "ROUND(SUM(o.product_revenue), 2) AS revenue" if has("revenue", "sales") else "COUNT(*) AS orders"
        return (f"SELECT d.year_month, {metric} FROM fact_orders o JOIN dim_date d ON d.date_key = o.date_key "
                f"WHERE {VALID}{yf} GROUP BY d.year_month ORDER BY d.year_month LIMIT 100")
    if has("late") and has("review", "rating", "score"):
        return ("SELECT CASE WHEN is_late = 1 THEN 'Late' ELSE 'On time' END AS delivery, "
                "ROUND(AVG(review_score), 2) AS avg_review, COUNT(*) AS orders FROM fact_orders o "
                f"WHERE is_late IS NOT NULL AND review_score IS NOT NULL{yf} GROUP BY 1 LIMIT 10")
    if has("late", "on-time", "on time") and has("deliver"):
        return ("SELECT CASE WHEN is_late = 1 THEN 'Late' ELSE 'On time' END AS delivery, "
                "ROUND(AVG(delivery_days), 1) AS avg_delivery_days, COUNT(*) AS orders FROM fact_orders o "
                f"WHERE is_late IS NOT NULL{yf} GROUP BY 1 LIMIT 10")
    if has("deliver"):
        return ("SELECT customer_state AS state, ROUND(AVG(delivery_days), 1) AS avg_delivery_days, "
                "ROUND(100.0 * AVG(is_late), 1) AS late_pct FROM fact_orders o "
                f"WHERE delivery_days IS NOT NULL{yf} GROUP BY customer_state ORDER BY avg_delivery_days DESC LIMIT 30")
    if has("payment"):
        return ("SELECT payment_type, COUNT(*) AS orders, ROUND(AVG(payment_value), 2) AS avg_order_value "
                f"FROM fact_orders o WHERE {VALID}{yf} GROUP BY payment_type ORDER BY orders DESC LIMIT 10")
    if has("more than once", "repeat", "returning"):
        return ("SELECT SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS repeat_customers, COUNT(*) AS total_customers, "
                "ROUND(100.0 * SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_rate_pct "
                f"FROM (SELECT customer_unique_id, COUNT(*) AS n FROM fact_orders o WHERE {VALID}{yf} "
                "GROUP BY customer_unique_id) t LIMIT 1")
    if has("customer") and has("state"):
        return ("SELECT customer_state AS state, COUNT(DISTINCT customer_unique_id) AS customers FROM fact_orders o "
                f"WHERE {VALID}{yf} GROUP BY customer_state ORDER BY customers DESC LIMIT {n}")
    if has("revenue", "sales", "total", "kpi", "overview"):
        return (f"SELECT ROUND(SUM(o.product_revenue), 2) AS revenue, COUNT(*) AS orders, "
                "COUNT(DISTINCT o.customer_unique_id) AS customers, "
                "ROUND(SUM(o.product_revenue) / COUNT(*), 2) AS avg_order_value "
                f"FROM fact_orders o WHERE {VALID}{yf} LIMIT 1")
    return None


def summarize(question: str, df: pd.DataFrame) -> str:
    """Plain-language summary without AI (first rows, top value)."""
    if df is None or df.empty:
        return "- No rows matched this question."
    lines = [f"- Returned **{len(df)}** row(s)."]
    first = df.iloc[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    label_cols = [c for c in df.columns if c not in num_cols]
    if label_cols and num_cols:
        lines.append(f"- Top result: **{first[label_cols[0]]}** with {num_cols[0]} = **{_fmt(first[num_cols[0]])}**.")
    elif num_cols:
        lines.append("- " + ", ".join(f"{c} = **{_fmt(first[c])}**" for c in num_cols))
    return "\n".join(lines)


def _fmt(v) -> str:
    try:
        return f"{float(v):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)

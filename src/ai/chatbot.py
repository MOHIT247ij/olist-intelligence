"""AI Chatbot: conversational assistant over the Olist data.

- Data questions  -> NL->SQL (Gemini) with built-in SQL fallback -> table + answer
- Other questions -> Gemini chat grounded in the project's KPIs (reports/summary.json)
- Gemini busy     -> still answers data questions with built-in SQL, and KPI questions offline
"""
import json
import re

from src import config
from src.ai import nl2sql
from src.ai.fallback_queries import match_builtin
from src.ai.gemini_client import generate

DATA_WORDS = ("revenue", "sales", "order", "customer", "state", "categor", "product", "review", "rating",
              "deliver", "late", "payment", "month", "trend", "top ", "how many", "average", "avg", "total",
              "seller", "freight", "city", "2016", "2017", "2018", "most", "least", "highest", "lowest")
EXPLAIN_WORDS = ("what is", "what are", "explain", "meaning", "why", "how does", "kya hai", "samjha",
                 "rfm", "churn", "forecast", "segment", "recommend", "suggest", "strategy", "improve", "insight",
                 "tips", "tip ", "badha", "kaise", "idea", "advice", "how to", "how can", "should")

SYSTEM = """You are "Data AI", a friendly data analyst chatbot inside Mohit's analytics project (dataset: {dataset}).
Answer briefly (max ~8 lines), use bullet points, and use ONLY the metrics given below for numbers.
If the user writes in Hinglish, reply in simple Hinglish. Never invent numbers.
Project metrics (currency {currency}; profit is an ESTIMATE unless a profit column exists):
{metrics}"""


def _summary() -> dict:
    f = config.REPORTS_DIR / "summary.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _meta() -> dict:
    m = _summary().get("meta", {})
    return {"dataset": m.get("dataset", "Olist Brazilian E-Commerce"), "currency": m.get("currency", "R$")}


def is_data_question(msg: str) -> bool:
    m = msg.lower()
    if any(w in m for w in EXPLAIN_WORDS) and not re.search(r"\btop\s+\d+|\bhow many\b|\bwhich\b", m):
        return False
    return any(w in m for w in DATA_WORDS)


def _offline_answer(msg: str) -> str:
    s = _summary()
    k = s.get("kpis", {})
    cur = _meta()["currency"]
    if not k:
        return "Gemini abhi busy hai. Thodi der baad try karo. 🙏"
    lines = ["Gemini abhi busy hai, isliye project ke saved numbers se jawab de raha hoon:",
             f"- Revenue: **{cur} {k['revenue']:,.0f}** | Orders: **{k['orders']:,}** | Customers: **{k['customers']:,}**",
             f"- AOV: **{cur} {k['aov']:,.2f}** | Repeat rate: **{k['repeat_customer_rate_pct']:.1f}%**",
             f"- Avg review: **{k['avg_review']:.2f}** | Late deliveries: **{k['late_delivery_pct']:.1f}%**"]
    ch = s.get("churn")
    if ch and "churn" in msg.lower():
        best = ch["metrics"][ch["best_model"]]
        lines.append(f"- Churn rate: **{ch['churn_rate']*100:.1f}%**, model ROC-AUC **{best['roc_auc']:.2f}**")
    return "\n".join(lines)


def reply(message: str, history: list[dict]) -> dict:
    """Returns {"text": str, "sql": str|None, "data": DataFrame|None}."""
    if is_data_question(message) or match_builtin(message) is not None and "?" in message:
        try:
            res = nl2sql.ask(message)
            if res.get("error") is None and res.get("data") is not None:
                return {"text": res.get("answer") or "Here is the result:", "sql": res["sql"], "data": res["data"]}
        except Exception:
            builtin = match_builtin(message)
            if builtin is not None:  # Gemini produced unusable SQL -> answer with built-in query
                try:
                    from src import db
                    from src.ai.fallback_queries import summarize
                    safe = nl2sql.validate_sql(builtin)
                    df = db.query(safe, readonly=True)
                    return {"text": summarize(message, df), "sql": safe, "data": df}
                except Exception:
                    pass  # fall through to chat
    convo = "\n".join(f"{t['role'].upper()}: {t['content'][:500]}" for t in history[-6:])
    metrics = json.dumps({k: v for k, v in _summary().items() if k != "delivery_vs_review"}, default=str)[:6000]
    try:
        text = generate(f"Conversation so far:\n{convo}\n\nUSER: {message}\nASSISTANT:",
                        system=SYSTEM.format(metrics=metrics, **_meta()), temperature=0.4)
    except Exception:
        text = _offline_answer(message)
    return {"text": text, "sql": None, "data": None}

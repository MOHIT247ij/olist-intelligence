"""AI-generated executive report from pipeline outputs (reports/summary.json)."""
import json
from datetime import date

from src import config
from src.ai.gemini_client import generate

SYSTEM = """You are the Head of Analytics for the business behind the dataset described in the metrics' "meta"
(default: Olist, a Brazilian e-commerce marketplace). Write for a CEO: crisp, numeric, action-oriented.
Use ONLY the numbers provided; never invent data. Use the currency given in meta.currency.
Profit figures are ESTIMATES (assumed margin) unless a profit column was mapped -- say so once.
Skip any section whose metrics are missing."""

TEMPLATE = """Using the JSON metrics below, write a Markdown executive report with these sections:
# <dataset name> Business Intelligence Report
## 1. Executive Summary (4 bullets)
## 2. Revenue & Profitability
## 3. Customers & Retention (RFM segments, repeat rate)
## 4. Churn Risk (model quality in plain words + top drivers)
## 5. Sales Forecast (next 12 weeks, accuracy vs baseline)
## 6. Products, Delivery & Customer Experience
## 7. Top 5 Recommendations (table: Action | Owner | Expected impact | Priority)
## 8. Data Caveats

METRICS:
{metrics}"""


def generate_report(summary: dict | None = None) -> str:
    if summary is None:
        summary = json.loads((config.REPORTS_DIR / "summary.json").read_text())
    md = generate(TEMPLATE.format(metrics=json.dumps(summary, indent=1, default=str)), system=SYSTEM,
                  temperature=0.3)
    path = config.REPORTS_DIR / f"ai_business_report_{date.today():%Y%m%d}.md"
    path.write_text(md, encoding="utf-8")
    return str(path)


def segment_playbook(segment: str, stats: dict) -> str:
    """Short AI marketing playbook for one RFM segment (used in the app)."""
    prompt = (f"RFM segment '{segment}' stats: {json.dumps(stats, default=str)}.\n"
              "Give a 5-bullet retention playbook: channel, offer, timing, KPI to track, one A/B test idea.")
    return generate(prompt, system=SYSTEM)


def summarize_complaints(samples: list[str], themes: list[dict]) -> str:
    """Gemini reads a sample of negative (Portuguese) reviews and returns English business insights."""
    prompt = ("Below are customer complaint themes (keyword-based counts) and a random sample of NEGATIVE "
              "Brazilian Portuguese reviews from an e-commerce marketplace.\n"
              f"THEMES: {json.dumps(themes, default=str)}\nSAMPLE REVIEWS:\n- " + "\n- ".join(samples[:40]) +
              "\n\nIn English, give: 1) Top 3 root causes of dissatisfaction (with 1 short translated example "
              "quote each), 2) 3 concrete actions for operations/sellers, 3) one KPI to track. Max 15 lines.")
    return generate(prompt, system=SYSTEM, temperature=0.3)

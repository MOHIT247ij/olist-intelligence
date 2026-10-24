"""Report helpers: offline (non-AI) executive report + tiny Markdown -> printable HTML converter."""
import html
import re


def offline_report(S: dict) -> str:
    k = S["kpis"]
    meta = S.get("meta", {})
    cur, name = meta.get("currency", "R$"), meta.get("dataset", "Olist")
    ch, fc = S.get("churn", {}), S.get("forecast", {})
    lines = [f"# {name} -- Business Intelligence Report", "",
             "_Standard report generated from pipeline metrics (profit = estimate, assumed margin)._", "",
             "## 1. Executive Summary",
             f"- Revenue **{cur} {k['revenue']:,.0f}** from **{k['orders']:,}** orders and **{k['customers']:,}** customers"
             f" (AOV {cur} {k['aov']:,.2f}).",
             f"- Only **{k['repeat_customer_rate_pct']:.1f}%** of customers buy again -> retention is the #1 growth lever.",
             f"- **{k['late_delivery_pct']:.1f}%** of deliveries are late; average review **{k['avg_review']:.2f}/5**.",
             f"- Freight is **{k['freight_share_pct']:.1f}%** of GMV.", "",
             "## 2. Top Categories", f"| Category | Revenue ({cur}) | Share % | Avg review |", "|---|---|---|---|"]
    for c in S.get("top_categories", [])[:8]:
        lines.append(f"| {c['category']} | {c['revenue']:,.0f} | {c['revenue_share_pct']:.1f} | "
                     f"{(c.get('avg_review') or 0):.2f} |")
    lines += ["", "## 3. Customer Segments (RFM)", "| Segment | Customers | Revenue share % | Action |",
              "|---|---|---|---|"]
    for r in S.get("rfm_segments", []):
        lines.append(f"| {r['segment']} | {r['customers']:,} | {r['revenue_share_pct']:.1f} | {r['recommended_action']} |")
    if ch:
        best = ch["metrics"][ch["best_model"]]
        lines += ["", "## 4. Churn Risk",
                  f"- Churn rate (no purchase within window): **{ch['churn_rate']*100:.1f}%**.",
                  f"- Best model: {ch['best_model'].replace('_', ' ')} -- ROC-AUC **{best['roc_auc']:.2f}**, "
                  f"top-decile lift **{best['top_decile_lift']:.1f}x**.",
                  "- Top drivers: " + ", ".join(d["feature"] for d in ch.get("top_drivers", [])[:4]) + "."]
    if fc:
        lines += ["", "## 5. Sales Forecast",
                  f"- Next 12 weeks: **{cur} {fc['next_12w_revenue']:,.0f}** (model MAPE {fc['model_mape_pct']:.1f}% vs "
                  f"baseline {fc['baseline_mape_pct']:.1f}%)."]
    se = S.get("sentiment") or {}
    if se:
        sh = se["share_pct"]
        lines += ["", "## 6. Customer Sentiment",
                  f"- Positive {sh.get('positive', 0):.1f}% · Neutral {sh.get('neutral', 0):.1f}% · "
                  f"Negative {sh.get('negative', 0):.1f}%.",
                  "- Top complaint themes: " + ", ".join(t["theme"] for t in se.get("top_complaint_themes", [])[:3]) + "."]
    lines += ["", "## 7. Recommendations", "| Action | Owner | Priority |", "|---|---|---|",
              "| Cut late deliveries in slow states (carrier SLAs, regional stock) | Operations | High |",
              "| 2nd-purchase coupon within 30 days for new customers | Marketing | High |",
              "| Win-back campaign for 'At Risk' high-value customers | CRM | Medium |",
              "| Coach / delist 'Needs Improvement' sellers | Marketplace | Medium |",
              "| Bundle categories with lift > 1 | Category | Low |",
              "", "## 8. Data Caveats",
              "- Profit uses an assumed margin (no cost data in Olist).",
              "- Data covers 2016-2018; last weeks are partial and excluded from forecasting."]
    return "\n".join(lines)


def _inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"(?<![\w*])_(.+?)_(?!\w)", r"<i>\1</i>", t)


def markdown_to_html(md: str, title: str = "Report") -> str:
    out, in_list, table = [], False, []

    def flush_table():
        if not table:
            return
        rows = [r for r in table if not re.match(r"^\|\s*-", r)]
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        h = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
        b = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
        out.append(f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>")
        table.clear()

    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("|"):
            table.append(s)
            continue
        flush_table()
        if re.match(r"^\s*[-*] ", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(re.sub(r'^\s*[-*] ', '', s))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,4}) (.*)", s)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif s:
            out.append(f"<p>{_inline(s)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#1d2433;"
           "line-height:1.5}h1{color:#0b3d91;border-bottom:3px solid #0b3d91;padding-bottom:6px}"
           "h2{color:#0b3d91;margin-top:28px}table{border-collapse:collapse;width:100%;margin:10px 0}"
           "th,td{border:1px solid #ccd3e0;padding:6px 8px;text-align:left;font-size:14px}th{background:#eef2fa}"
           "@media print{body{margin:0}}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(out)}</body></html>")

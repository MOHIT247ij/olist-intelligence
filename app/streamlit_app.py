"""Olist AI-Powered E-Commerce Intelligence Platform -- Streamlit app.

  streamlit run app/streamlit_app.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402

st.set_page_config(page_title="Olist Intelligence", page_icon="📊", layout="wide")

# ---------------------------------------------------------------- dataset switcher (Olist or any uploaded file)
from contextlib import contextmanager  # noqa: E402

from src import db, universal  # noqa: E402

if not hasattr(config, "_DEFAULTS"):
    config._DEFAULTS = (config.PROCESSED_DIR, config.REPORTS_DIR, config.SQLITE_PATH)
OLIST = "🇧🇷 Olist Brazilian E-Commerce (default)"
workspaces = universal.list_workspaces()
labels = [OLIST] + [f"📁 {w['dataset']}" for w in workspaces]
slugs = [None] + [w["slug"] for w in workspaces]
cur = st.session_state.get("dataset")
idx = slugs.index(cur) if cur in slugs else 0
with st.sidebar:
    st.header("🗂️ Dataset")
    choice = st.radio("All dashboards use:", labels, index=idx)
    active = slugs[labels.index(choice)]
    st.session_state["dataset"] = active
    if active:
        _, proc_dir, rep_dir, db_path = universal.workspace_dirs(active)
        config.PROCESSED_DIR, config.REPORTS_DIR, config.SQLITE_PATH = proc_dir, rep_dir, db_path
        if st.button("🗑️ Delete this dataset"):
            universal.delete_workspace(active)
            st.session_state["dataset"] = None
            st.cache_data.clear()
            st.rerun()
    else:
        config.PROCESSED_DIR, config.REPORTS_DIR, config.SQLITE_PATH = config._DEFAULTS
    st.caption("Upload any sales file in **📤 Upload & Analyze** → *Build ALL dashboards* to add it here.")

P = config.PROCESSED_DIR


@st.cache_data
def _load(folder: str, name: str, dates: tuple):
    f = Path(folder) / f"{name}.csv"
    return pd.read_csv(f, parse_dates=list(dates)) if f.exists() else pd.DataFrame()


def load(name: str, dates=()):
    return _load(str(P), name, tuple(dates))


db.ensure_sqlite()  # cloud deploy: rebuild local SQLite from data/processed CSVs if missing

summary_path = config.REPORTS_DIR / "summary.json"
if summary_path.exists():
    S = json.loads(summary_path.read_text())
else:
    st.warning("No outputs yet for this dataset. Run `run_pipeline.bat` (Olist) or upload a file below.")
    S = {"kpis": {}}
K = S["kpis"]
META = S.get("meta", {"dataset": "Olist Brazilian E-Commerce", "currency": "R$"})
CUR = META.get("currency", "R$")
CAPS = META.get("capabilities")  # None for Olist = everything available


def brl(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if x != x:  # NaN
        return "—"
    return f"{CUR} {x/1e6:,.2f}M" if abs(x) >= 1e6 else f"{CUR} {x:,.0f}"


TAB_NEEDS = {"👥 Customers & RFM": "RFM / Cohorts / CLV / Churn", "🔥 Cohorts & CLV": "RFM / Cohorts / CLV / Churn",
             "⚠️ Churn": "RFM / Cohorts / CLV / Churn", "🔮 Forecast": "Forecast & anomaly alerts",
             "🛍️ Products & Basket": "Products & Pareto", "🏪 Sellers": "Seller scorecard",
             "😊 Reviews": "Reviews & sentiment", "🌎 Geography": "Geography", "🧪 What-if": "Delivery & what-if"}
HINT = {"RFM / Cohorts / CLV / Churn": "a Customer ID column", "Products & Pareto": "a Product/Category column",
        "Seller scorecard": "a Seller/Store column", "Reviews & sentiment": "a Rating or Review text column",
        "Geography": "a Region/State/City column", "Delivery & what-if": "Delivery date + Promised date + Rating columns",
        "Forecast & anomaly alerts": "Date + Amount columns"}


@contextmanager
def guard(tab: str):
    """Shows a friendly message instead of crashing when the active dataset can't support a section."""
    need = TAB_NEEDS.get(tab)
    if CAPS is not None and need and not CAPS.get(need, True):
        st.info(f"ℹ️ **{tab}** isn't available for *{META.get('dataset')}* -- it needs {HINT.get(need, 'more columns')}. "
                "Go to 📤 Upload & Analyze and map that column, then rebuild.")
    try:
        yield
    except Exception as e:  # noqa: BLE001
        if CAPS is None or not need or CAPS.get(need, True):
            st.info(f"ℹ️ Part of this section isn't available for this dataset ({type(e).__name__}).")


def _fallback(tab: str) -> bool:
    """Render an alternative analysis when the dataset lacks the columns a tab normally needs.
    Returns True if the normal tab body should be skipped."""
    need = TAB_NEEDS.get(tab)
    if tab == "🧪 What-if":
        _revenue_simulator()
        return CAPS is not None and not CAPS.get(need, True)
    if CAPS is None or not need or CAPS.get(need, True):
        return False
    from src import fallbacks as F
    items = load("fact_order_items", ["purchase_date"])
    if items.empty:
        st.info("Build the dashboards from 📤 Upload & Analyze first.")
        return True
    col = F.group_col(items)
    nice = (META.get("mapping") or {}).get({"category": "product", "customer_state": "region",
                                             "seller_id": "seller"}[col], col)
    st.caption(f"ℹ️ This file doesn't have {HINT.get(need, 'the matching column')} -- showing the closest analysis using "
               f"**{nice}** instead.")
    if items[col].nunique() <= 1:
        m = load("agg_monthly_revenue", ["month"])
        st.plotly_chart(px.bar(m, x="month", y="revenue", title="Monthly revenue"), use_container_width=True)
        st.dataframe(m.round(2), hide_index=True, use_container_width=True)
        return True
    if tab == "👥 Customers & RFM":
        seg = F.segment_analysis(items, col).rename(columns={col: nice})
        st.subheader(f"👥 Segment analysis by {nice} (ABC)")
        c1, c2 = st.columns([3, 2])
        c1.plotly_chart(px.treemap(seg.head(40), path=["segment", nice], values="revenue", color="aov",
                                   title=f"Revenue by {nice} (A = top 80%)"), use_container_width=True)
        c2.dataframe(seg.groupby("segment", observed=True).agg(groups=(nice, "count"), revenue=("revenue", "sum"))
                     .reset_index(), hide_index=True, use_container_width=True)
        st.dataframe(seg.round(2), hide_index=True, use_container_width=True)
    elif tab == "🔥 Cohorts & CLV":
        hm = F.month_heatmap(items, col)
        st.subheader(f"🔥 Monthly revenue heatmap by {nice}")
        st.plotly_chart(px.imshow(hm, aspect="auto", color_continuous_scale="Blues",
                                  labels=dict(x="Month", y=nice, color="Revenue")), use_container_width=True)
        seg = F.segment_analysis(items, col).rename(columns={col: nice})
        st.subheader(f"💰 Lifetime value by {nice}")
        st.plotly_chart(px.bar(seg.head(20), x=nice, y="revenue", color="segment",
                               title=f"Total value per {nice}"), use_container_width=True)
    elif tab == "⚠️ Churn":
        dec = F.declining_segments(items, col).rename(columns={col: nice})
        st.subheader(f"⚠️ Declining {nice} (last 3 months vs previous 3)")
        if dec.empty:
            st.info("Not enough history to compare periods.")
        else:
            c = st.columns(3)
            for i, r in enumerate(["High", "Medium", "Low / growing"]):
                c[i].metric(f"{r} risk", int((dec["risk"] == r).sum()))
            st.plotly_chart(px.bar(dec.head(25), x="change_pct", y=nice, orientation="h", color="risk",
                                   title="Revenue change %").update_yaxes(autorange="reversed", type="category"),
                            use_container_width=True)
            st.dataframe(dec.round(1), hide_index=True, use_container_width=True)
    elif tab in ("😊 Reviews", "🏪 Sellers"):
        pr = F.performance_ratings(items, col).rename(columns={col: nice})
        st.subheader(f"⭐ Performance rating by {nice} (from revenue, growth & margin)")
        st.plotly_chart(px.bar(pr.head(25), x="stars", y=nice, orientation="h", color="stars", range_x=[0, 5],
                               color_continuous_scale="RdYlGn").update_yaxes(autorange="reversed", type="category"),
                        use_container_width=True)
        st.dataframe(pr[[nice, "stars", "revenue", "growth_pct", "margin_pct", "orders", "aov"]].round(2),
                     hide_index=True, use_container_width=True)
    elif tab in ("🌎 Geography", "🛍️ Products & Basket"):
        seg = F.segment_analysis(items, col).rename(columns={col: nice})
        st.plotly_chart(px.bar(seg.head(20), x=nice, y="revenue", color="segment",
                               title=f"Revenue by {nice}"), use_container_width=True)
        st.dataframe(seg.round(2), hide_index=True, use_container_width=True)
    return True


def _revenue_simulator():
    from src import fallbacks as F
    if not K:
        return
    st.subheader("💹 Revenue simulator")
    c1, c2, c3 = st.columns(3)
    o = c1.slider("Change in number of orders (%)", -50, 100, 10, key="sim_o")
    a = c2.slider("Change in average order value (%)", -50, 100, 5, key="sim_a")
    base_margin = K["est_gross_profit"] / K["revenue"] * 100 if K.get("revenue") else 0
    mg = c3.slider("Change in profit margin (pp)", -20, 20, 0, key="sim_m")
    r = F.revenue_simulator(K, o, a, mg, base_margin)
    c = st.columns(4)
    for col, (lab, key, money) in zip(c, [("Revenue", "revenue", True), ("Orders", "orders", False),
                                          ("Avg order value", "aov", True), ("Profit (est.)", "profit", True)]):
        old, new = r[key]
        col.metric(lab, brl(new) if money else f"{new:,.0f}", f"{(new / old - 1) * 100 if old else 0:+.1f}%")
    st.divider()


title = "Olist E-Commerce Intelligence & Customer Retention Platform" if not CAPS else \
    f"{META.get('dataset')} — Intelligence Platform"
st.title(f"🏆 {title}")
st.caption("PostgreSQL · Python ETL & ML · Power BI · Gemini AI  |  Profit = estimate unless a profit column was "
           f"mapped (assumed gross margin {config.ASSUMED_GROSS_MARGIN:.0%})")

NAMES = ["📤 Upload & Analyze", "📊 Executive", "👥 Customers & RFM", "🔥 Cohorts & CLV", "⚠️ Churn", "🔮 Forecast",
         "🛍️ Products & Basket", "🏪 Sellers", "😊 Reviews", "🌎 Geography", "🧪 What-if",
         "💬 AI Chatbot", "🤖 AI Analyst"]
T = dict(zip(NAMES, st.tabs(NAMES)))

# ---------------------------------------------------------------- Upload & Analyze (any dataset)
@st.cache_data(show_spinner=False)
def _analyze(data: bytes, name: str):
    from src import auto_analyzer as A
    raw = A.load_file(data, name)
    d, log = A.clean(raw)
    prof = A.profile(d)
    return raw.shape, d, log, prof, A.insights(d, prof)


with T["📤 Upload & Analyze"]:
    st.subheader("📤 Upload any dataset → automatic analysis")
    st.caption("CSV · TSV · Excel · JSON · Parquet. Cleaning, profiling, KPIs, charts, insights, AI Q&A and a "
               "downloadable report -- all automatic. Upload the 9 Olist Kaggle CSVs to rebuild this whole dashboard.")
    if st.session_state.get("just_built"):
        st.success(f"✅ **{st.session_state.pop('just_built')}** is ready -- every tab (Executive, RFM, Churn, "
                   "Forecast, Products, Sellers, Reviews, What-if, Chatbot...) now shows this file. "
                   "Switch datasets anytime from the left sidebar.")
    ups = st.file_uploader("Drop file(s) here", type=["csv", "tsv", "txt", "xlsx", "xls", "json", "parquet"],
                           accept_multiple_files=True)
    if ups:
        olist_names = set(config.RAW_FILES.values())
        olist_up = [u for u in ups if u.name in olist_names]
        if olist_up:
            st.info(f"🛒 Detected **{len(olist_up)}/9 Olist files**. Save them and rebuild the full dashboard "
                    "(ETL + RFM + churn + forecast + sentiment...).")
            if st.button("💾 Save & run full Olist pipeline", type="primary"):
                for u in olist_up:
                    (config.RAW_DIR / u.name).write_bytes(u.getvalue())
                missing = [f for f in olist_names if not (config.RAW_DIR / f).exists()]
                if missing:
                    st.error(f"Still missing in data/raw: {missing}")
                else:
                    import pipeline as _pl
                    with st.spinner("Running full pipeline on the new data (3-5 min for real Olist data)..."):
                        try:
                            if config.SQLITE_PATH.exists():
                                config.SQLITE_PATH.unlink()
                            _pl.main()
                            st.cache_data.clear()
                            st.success("✅ Done! All tabs now use the new data. Refresh the page (F5).")
                        except Exception as e:
                            st.error(f"Pipeline failed: {e}")
        names = [u.name for u in ups]
        pick = st.selectbox("Analyze file", names) if len(ups) > 1 else names[0]
        up = ups[names.index(pick)]
        from src import auto_analyzer as A
        try:
            with st.spinner(f"Analyzing {up.name}..."):
                raw_shape, d, log, prof, ins = _analyze(up.getvalue(), up.name)
        except Exception as e:
            st.error(f"Could not analyze this file: {e}")
            d = None
        if d is not None:
            r = A.roles(prof)
            k = A.kpis(d, r)
            cols = st.columns(len(k))
            for c, (lab, val) in zip(cols, k):
                c.metric(lab, val)
            with st.expander(f"🧹 Cleaning steps ({len(log)}) -- original {raw_shape[0]:,} × {raw_shape[1]}"):
                for x in log:
                    st.write("• " + x)
            st.markdown("#### 💡 Key insights")
            for x in ins:
                st.markdown("- " + x)

            # ---------- make EVERY dashboard tab use this file
            with st.expander("🚀 Use this file for ALL dashboards (RFM, churn, forecast, sellers, reviews, AI...)",
                             expanded=True):
                st.caption("Columns are auto-detected -- fix any wrong ones, then click **Build**. Only *Date* and "
                           "*Amount* are required; every extra column unlocks more dashboards.")
                det = universal.detect_mapping(d, prof)
                opts = ["— none —"] + list(d.columns)
                mapping = {}
                mcols = st.columns(4)
                for i, (role, (label, _)) in enumerate(universal.ROLES.items()):
                    default = det.get(role)
                    sel = mcols[i % 4].selectbox(label + (" *" if role in ("date", "amount") else ""), opts,
                                                 index=opts.index(default) if default in opts else 0,
                                                 key=f"map_{up.name}_{role}")
                    if sel != "— none —":
                        mapping[role] = sel
                caps = universal.capabilities(mapping)
                auto_key = f"auto_{up.name}_{len(d)}_{d.shape[1]}"
                if "date" in mapping and "amount" in mapping and not st.session_state.get(auto_key):
                    st.session_state[auto_key] = True           # build automatically, once per file
                    auto_name = Path(up.name).stem.replace("_", " ").title()
                    with st.spinner("⚙️ Auto-building ALL dashboards from this file..."):
                        try:
                            universal.run_workspace(d, mapping, auto_name, "₹", up.name)
                            st.session_state["dataset"] = universal.slug(auto_name)
                            st.session_state["just_built"] = auto_name
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Auto-build failed: {e}")
                elif "date" not in mapping or "amount" not in mapping:
                    st.warning("Dashboards need at least a **Date** and an **Amount/Sales** column -- choose them "
                               "below. (The analysis on this tab works anyway.)")
                st.markdown("**Full analysis:** " + " · ".join(("✅ " if v else "🟡 ") + k for k, v in caps.items()))
                st.caption("🟡 = column missing → that tab shows the closest alternative analysis instead.")
                c1, c2, c3 = st.columns([3, 1, 2])
                ds_name = c1.text_input("Dataset name", value=Path(up.name).stem.replace("_", " ").title(),
                                        key=f"name_{up.name}")
                cur_sym = c2.selectbox("Currency", ["₹", "$", "€", "£", "R$", "¥", ""], key=f"cur_{up.name}")
                if c3.button("🔄 Rebuild with these settings", type="primary", key=f"build_{up.name}"):
                    if "date" not in mapping or "amount" not in mapping:
                        st.error("Please choose at least the Date and Amount columns.")
                    else:
                        with st.spinner("Building star schema + running every analysis on your file..."):
                            try:
                                res = universal.run_workspace(d, mapping, ds_name, cur_sym, up.name)
                                st.session_state["dataset"] = universal.slug(ds_name)
                                st.cache_data.clear()
                                skipped = res.get("unavailable", {})
                                st.success("✅ Done! Every tab now shows **" + ds_name + "**. "
                                           + (f"(Skipped: {', '.join(skipped)})" if skipped else ""))
                                st.rerun()
                            except Exception as e:
                                st.error(f"Could not build dashboards: {e}")

            sub = st.tabs(["📈 Charts", "🛠️ Build your chart", "📋 Column profile", "🔎 Data preview", "🤖 AI"])
            measure = A.main_measure(d, r["numeric"])
            with sub[0]:
                if r["date"]:
                    dcol = r["date"][0]
                    ts = d.dropna(subset=[dcol]).set_index(dcol)
                    ts = (ts[measure] if measure else ts.assign(rows=1)["rows"]).resample("MS").sum().reset_index()
                    st.plotly_chart(px.line(ts, x=dcol, y=ts.columns[1], markers=True,
                                            title=f"Monthly {ts.columns[1]}"), use_container_width=True)
                cc = st.columns(2)
                for i, cat in enumerate(r["category"][:4]):
                    if measure:
                        g = d.groupby(cat, observed=True)[measure].sum().nlargest(15).reset_index()
                        fig = px.bar(g, x=measure, y=cat, orientation="h", title=f"{measure} by {cat} (top 15)")
                    else:
                        g = d[cat].value_counts().head(15).rename_axis(cat).reset_index(name="count")
                        fig = px.bar(g, x="count", y=cat, orientation="h", title=f"Rows by {cat} (top 15)")
                    cc[i % 2].plotly_chart(fig.update_yaxes(autorange="reversed", type="category"),
                                           use_container_width=True)
                for i, num in enumerate(r["numeric"][:4]):
                    cc[i % 2].plotly_chart(px.histogram(d, x=num, nbins=40, title=f"Distribution of {num}"),
                                           use_container_width=True)
                if len(r["numeric"]) >= 2:
                    st.plotly_chart(px.imshow(d[r["numeric"][:12]].corr(), text_auto=".2f", aspect="auto",
                                              color_continuous_scale="RdBu", zmin=-1, zmax=1,
                                              title="Correlation matrix"), use_container_width=True)
            with sub[1]:
                c1, c2, c3, c4 = st.columns(4)
                kind = c1.selectbox("Chart", ["Bar", "Line", "Scatter", "Pie", "Box", "Histogram"])
                x = c2.selectbox("X axis", list(d.columns))
                ys = ["(count)"] + r["numeric"]
                y = c3.selectbox("Y axis", ys, index=ys.index(measure) if measure in ys else 0)
                agg = c4.selectbox("Aggregate", ["sum", "mean", "median", "max", "min"])
                try:
                    if kind in ("Bar", "Line", "Pie"):
                        g = (d.groupby(x, observed=True).size().reset_index(name="count") if y == "(count)" else
                             d.groupby(x, observed=True)[y].agg(agg).reset_index())
                        yv = "count" if y == "(count)" else y
                        if kind == "Bar":
                            g = g.nlargest(30, yv) if not pd.api.types.is_datetime64_any_dtype(g[x]) else g
                            fig = px.bar(g, x=x, y=yv)
                        elif kind == "Line":
                            fig = px.line(g.sort_values(x), x=x, y=yv, markers=True)
                        else:
                            fig = px.pie(g.nlargest(12, yv), names=x, values=yv, hole=.4)
                    elif kind == "Scatter":
                        fig = px.scatter(d.sample(min(len(d), 5000), random_state=1), x=x,
                                         y=None if y == "(count)" else y, opacity=.6)
                    elif kind == "Box":
                        fig = px.box(d, x=x, y=None if y == "(count)" else y)
                    else:
                        fig = px.histogram(d, x=x, nbins=40)
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.warning(f"Can't draw this combination: {e}")
            with sub[2]:
                st.dataframe(prof, hide_index=True, use_container_width=True)
            with sub[3]:
                st.dataframe(d.head(500), use_container_width=True)
                st.download_button("⬇️ Download cleaned data (CSV)", d.to_csv(index=False).encode("utf-8"),
                                   f"cleaned_{Path(up.name).stem}.csv", mime="text/csv")
            with sub[4]:
                if not config.GEMINI_API_KEY:
                    st.warning("Add GEMINI_API_KEY to env.txt to enable AI features for uploaded files.")
                key = f"ai_{up.name}_{len(d)}"
                if st.button("🧠 AI summary of this dataset"):
                    with st.spinner("Gemini is studying your data..."):
                        try:
                            st.session_state[key] = A.ai_summary(d, prof, ins, up.name)
                        except Exception as e:
                            st.warning(f"Gemini unavailable right now ({str(e)[:120]})")
                if st.session_state.get(key):
                    st.markdown(st.session_state[key])
                q = st.text_input("💬 Ask a question about this file", placeholder="e.g. Total sales by region")
                if st.button("Ask file") and q:
                    with st.spinner("Writing SQL on your file..."):
                        try:
                            res = A.ask(q, d, A.to_sqlite(d))
                            st.code(res["sql"], language="sql")
                            st.dataframe(res["data"], use_container_width=True, hide_index=True)
                            if res["answer"]:
                                st.markdown(res["answer"])
                        except Exception as e:
                            st.warning(f"Could not answer: {str(e)[:200]}")
            from src.report import markdown_to_html
            md = A.markdown_report(up.name, d, prof, log, ins, st.session_state.get(f"ai_{up.name}_{len(d)}"))
            st.download_button("📄 Download analysis report (HTML → Ctrl+P → Save as PDF)",
                               markdown_to_html(md, f"Analysis - {up.name}"), f"report_{Path(up.name).stem}.html",
                               mime="text/html")
    else:
        st.info("👆 Upload a file to start. Try any sales, HR, finance or survey dataset!")

# ---------------------------------------------------------------- Executive
with T["📊 Executive"]:
    if not _fallback("📊 Executive"):
        with guard("📊 Executive"):
            c = st.columns(6)
            c[0].metric("Revenue", brl(K["revenue"]))
            c[1].metric("Est. Gross Profit", brl(K["est_gross_profit"]))
            c[2].metric("Orders", f"{K['orders']:,}")
            c[3].metric("Customers", f"{K['customers']:,}")
            c[4].metric("AOV", brl(K["aov"]))
            c[5].metric("Repeat Rate", f"{K['repeat_customer_rate_pct']:.1f}%")
            c = st.columns(4)
            c[0].metric("Avg Review", f"{K['avg_review']:.2f} ★")
            c[1].metric("Late Deliveries", f"{K['late_delivery_pct']:.1f}%")
            c[2].metric("Avg Delivery", f"{K['avg_delivery_days']:.1f} days")
            c[3].metric("Freight Share of GMV", f"{K['freight_share_pct']:.1f}%")
            an = load("agg_revenue_anomalies", ["week"])
            if not an.empty:
                alerts = an[an["alert"].fillna("") != ""].tail(3)
                for _, a in alerts.iloc[::-1].iterrows():
                    icon, fn = ("🔻", st.error) if a["alert"] == "Drop" else ("🚀", st.success)
                    fn(f"{icon} **Revenue {a['alert']}** -- week of {a['week']:%d %b %Y}: {brl(a['revenue'])} "
                       f"({a['change_pct']:+.0f}% vs expected {brl(a['expected'])})")
                with st.expander("🚨 Anomaly detection (weekly revenue, rolling z-score)"):
                    fig = go.Figure()
                    fig.add_scatter(x=an["week"], y=an["revenue"], name="Revenue", mode="lines")
                    fig.add_scatter(x=an["week"], y=an["expected"], name="Expected (8-wk avg)", mode="lines",
                                    line=dict(dash="dot"))
                    pts = an[an["alert"].fillna("") != ""]
                    fig.add_scatter(x=pts["week"], y=pts["revenue"], mode="markers", name="Alert",
                                    marker=dict(size=11, symbol="x"), text=pts["alert"])
                    fig.update_layout(height=320, legend=dict(orientation="h"))
                    st.plotly_chart(fig, use_container_width=True)
            m = load("agg_monthly_revenue", ["month"])
            fig = go.Figure()
            fig.add_bar(x=m["month"], y=m["revenue"], name="Revenue")
            fig.add_scatter(x=m["month"], y=m["revenue_3m_ma"], name="3-month avg", mode="lines")
            fig.update_layout(title="Monthly revenue", height=380, legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)
            col1, col2 = st.columns(2)
            dv = load("agg_delivery_review")
            col1.plotly_chart(px.bar(dv, x="delivery_bucket", y="avg_review", text_auto=".2f",
                                     title="Late delivery kills reviews"), use_container_width=True)
            pay = load("agg_payment")
            col2.plotly_chart(px.pie(pay, names="payment_type", values="orders", hole=.5, title="Payment mix"),
                              use_container_width=True)

# ---------------------------------------------------------------- Customers
with T["👥 Customers & RFM"]:
    if not _fallback("👥 Customers & RFM"):
        with guard("👥 Customers & RFM"):
            seg = load("agg_rfm_segments")
            col1, col2 = st.columns([3, 2])
            col1.plotly_chart(px.treemap(seg, path=["segment"], values="customers", color="revenue_share_pct",
                                         color_continuous_scale="Blues", title="RFM segments (size = customers)"),
                              use_container_width=True)
            col2.dataframe(seg[["segment", "customers", "customer_share_pct", "revenue_share_pct", "recommended_action"]]
                           .round(1), hide_index=True, use_container_width=True)
            rfm = load("customer_rfm")
            st.plotly_chart(px.scatter(rfm.sample(min(len(rfm), 5000), random_state=1), x="recency_days", y="monetary",
                                       color="segment", log_y=True, opacity=.6, title="Recency vs Monetary"),
                            use_container_width=True)

# ---------------------------------------------------------------- Churn
with T["⚠️ Churn"]:
    if not _fallback("⚠️ Churn"):
        with guard("⚠️ Churn"):
            ch = S["churn"]
            best = ch["metrics"][ch["best_model"]]
            c = st.columns(4)
            c[0].metric("Churn rate (label)", f"{ch['churn_rate']*100:.1f}%")
            c[1].metric("ROC-AUC", f"{best['roc_auc']:.3f}")
            c[2].metric("Top-decile lift", f"{best['top_decile_lift']:.1f}x")
            c[3].metric("Best model", ch["best_model"].replace("_", " ").title())
            st.info("Churn = no purchase in the next "
                    f"{config.CHURN_WINDOW_DAYS} days after cutoff {ch['cutoff']}. Features use only data before cutoff "
                    "(no leakage). Lift = how much better than random the model finds customers who will return.")
            col1, col2 = st.columns(2)
            fi = load("churn_feature_importance")
            col1.plotly_chart(px.bar(fi.head(10), x="importance", y="feature", orientation="h",
                                     title="Top churn drivers (permutation importance)").update_yaxes(autorange="reversed"),
                              use_container_width=True)
            sc = load("customer_churn_scores")
            col2.plotly_chart(px.histogram(sc, x="churn_probability", color="risk_tier", nbins=40,
                                           title="Churn probability distribution"), use_container_width=True)
            st.subheader("High-value customers at risk")
            st.dataframe(sc.head(50).round(3), hide_index=True, use_container_width=True)
            st.download_button("Download scores (CSV)", sc.to_csv(index=False), "churn_scores.csv")

# ---------------------------------------------------------------- Forecast
with T["🔮 Forecast"]:
    if not _fallback("🔮 Forecast"):
        with guard("🔮 Forecast"):
            h = load("revenue_weekly", ["week"])
            f = load("forecast_weekly", ["week"])
            fig = go.Figure()
            fig.add_scatter(x=h["week"], y=h["revenue"], name="Actual", mode="lines")
            fig.add_scatter(x=f["week"], y=f["upper"], line=dict(width=0), showlegend=False)
            fig.add_scatter(x=f["week"], y=f["lower"], fill="tonexty", line=dict(width=0), name="80% band")
            fig.add_scatter(x=f["week"], y=f["forecast"], name="Forecast", mode="lines", line=dict(dash="dash"))
            fig.update_layout(title="Weekly revenue -- 12-week forecast", height=420)
            st.plotly_chart(fig, use_container_width=True)
            fc = S["forecast"]
            c = st.columns(3)
            c[0].metric("Next 12 weeks", brl(fc["next_12w_revenue"]))
            c[1].metric("Model MAPE", f"{fc['model_mape_pct']:.1f}%")
            c[2].metric("Baseline MAPE", f"{fc['baseline_mape_pct']:.1f}%")

# ---------------------------------------------------------------- Products
with T["🛍️ Products & Basket"]:
    if not _fallback("🛍️ Products & Basket"):
        with guard("🛍️ Products & Basket"):
            cat = load("agg_category")
            st.plotly_chart(px.bar(cat.head(15), x="revenue", y="category", orientation="h", color="pareto_class",
                                   title="Top 15 categories (ABC / Pareto class)").update_yaxes(autorange="reversed"),
                            use_container_width=True)
            st.plotly_chart(px.scatter(cat, x="avg_price", y="avg_review", size="revenue", color="pareto_class",
                                       hover_name="category", title="Price vs review (bubble = revenue)"),
                            use_container_width=True)

            st.subheader("🛒 Market Basket -- which categories are bought together?")
            mb = load("agg_market_basket")
            bs = S.get("market_basket", {})
            if bs:
                c = st.columns(2)
                c[0].metric("Orders with 2+ items", f"{bs['multi_item_pct']:.1f}%")
                c[1].metric("Orders with 2+ categories", f"{bs['multi_category_pct']:.1f}%")
            if mb.empty:
                st.info("Not enough multi-category orders to find patterns.")
            else:
                st.caption("Lift > 1 = bought together more often than chance → bundle / cross-sell candidates.")
                mb["pair"] = mb["category_a"] + " + " + mb["category_b"]
                st.plotly_chart(px.bar(mb.head(15), x="lift", y="pair", orientation="h", color="orders_together",
                                       title="Top category pairs by lift").update_yaxes(autorange="reversed"),
                                use_container_width=True)
                st.dataframe(mb.drop(columns="pair").head(30).round(2), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- Geography
with T["🌎 Geography"]:
    if not _fallback("🌎 Geography"):
        with guard("🌎 Geography"):
            stt = load("agg_state")
            col1, col2 = st.columns(2)
            col1.plotly_chart(px.bar(stt, x="state", y="revenue", title="Revenue by state"), use_container_width=True)
            col2.plotly_chart(px.scatter(stt, x="avg_delivery_days", y="avg_review", size="orders", text="state",
                                         title="Delivery time vs review by state"), use_container_width=True)
            st.dataframe(stt.round(2), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- Cohorts & CLV
with T["🔥 Cohorts & CLV"]:
    if not _fallback("🔥 Cohorts & CLV"):
        with guard("🔥 Cohorts & CLV"):
            st.subheader("🔥 Monthly cohort retention")
            st.caption("Row = month of first purchase · Column = months since first purchase · Value = % customers who "
                       "bought again in that month")
            co = load("agg_cohort_retention")
            if not co.empty:
                mat = co.pivot(index="cohort_month", columns="month_number", values="retention_pct").fillna(0)
                disp = mat.drop(columns=0, errors="ignore")
                st.plotly_chart(px.imshow(disp, text_auto=".1f", aspect="auto", color_continuous_scale="Blues",
                                          labels=dict(x="Months since first purchase", y="Cohort", color="Retention %"),
                                          title="Retention % by cohort (month 0 = 100%, hidden)"), use_container_width=True)
                if S.get("cohort", {}).get("avg_month1_retention_pct") is not None:
                    st.metric("Avg month-1 retention", f"{S['cohort']['avg_month1_retention_pct']:.2f}%")
            st.divider()
            st.subheader("💰 Customer Lifetime Value (CLV)")
            st.caption("CLV = historical spend + predicted next-12-month spend "
                       "(return probability from churn model × avg order value × expected orders).")
            tiers = load("agg_clv_tiers")
            if not tiers.empty:
                col1, col2 = st.columns(2)
                col1.plotly_chart(px.bar(tiers, x="clv_tier", y="clv_share_pct", text_auto=".1f",
                                         title="Share of total CLV by tier (%)"), use_container_width=True)
                col2.dataframe(tiers.round(1), hide_index=True, use_container_width=True)
            clv = load("customer_clv")
            if not clv.empty:
                st.markdown("**Top 25 customers by CLV**")
                st.dataframe(clv.sort_values("total_clv", ascending=False).head(25).round(2), hide_index=True,
                             use_container_width=True)

# ---------------------------------------------------------------- Sellers
with T["🏪 Sellers"]:
    if not _fallback("🏪 Sellers"):
        with guard("🏪 Sellers"):
            sc = load("agg_seller_scorecard")
            if sc.empty:
                st.info("Seller scorecard not available for this dataset.")
            else:
                st.caption("Score (0-100) = 35% review + 25% on-time delivery + 25% revenue + 15% delivery speed "
                           "(percentile ranks, sellers with 10+ orders).")
                c = st.columns(4)
                for i, t in enumerate(["Top Seller", "Good", "Average", "Needs Improvement"]):
                    c[i].metric(t, int((sc["tier"] == t).sum()))
                col1, col2 = st.columns(2)
                col1.plotly_chart(px.scatter(sc, x="late_pct", y="avg_review", size="revenue", color="tier",
                                             hover_data=["seller_id", "city", "state"],
                                             title="Late % vs review (bubble = revenue)"), use_container_width=True)
                col2.plotly_chart(px.histogram(sc, x="score", color="tier", nbins=30, title="Score distribution"),
                                  use_container_width=True)
                tier = st.selectbox("Filter by tier", ["All", "Top Seller", "Good", "Average", "Needs Improvement"])
                view = sc if tier == "All" else sc[sc["tier"] == tier]
                st.dataframe(view.round(2), hide_index=True, use_container_width=True)
                st.download_button("Download scorecard (CSV)", sc.to_csv(index=False), "seller_scorecard.csv")

# ---------------------------------------------------------------- Reviews / Sentiment
with T["😊 Reviews"]:
    if not _fallback("😊 Reviews"):
        with guard("😊 Reviews"):
            se = S.get("sentiment") or {}
            if not se:
                st.info("Review sentiment not available for this dataset.")
            else:
                sh = se["share_pct"]
                c = st.columns(4)
                c[0].metric("😊 Positive", f"{sh.get('positive', 0):.1f}%")
                c[1].metric("😐 Neutral", f"{sh.get('neutral', 0):.1f}%")
                c[2].metric("😞 Negative", f"{sh.get('negative', 0):.1f}%")
                c[3].metric("Reviews with text", f"{se['reviews_with_text_pct']:.1f}%")
                sm = load("agg_sentiment_month")
                if not sm.empty:
                    fig = go.Figure()
                    for k, col in (("positive", "#2e7d32"), ("neutral", "#9e9e9e"), ("negative", "#c62828")):
                        fig.add_scatter(x=sm["review_month"], y=sm[f"{k}_pct"], name=k.title(), mode="lines",
                                        line=dict(color=col))
                    fig.update_layout(title="Sentiment share by month (%)", height=360, legend=dict(orientation="h"))
                    st.plotly_chart(fig, use_container_width=True)
                th = load("agg_complaint_themes")
                if not th.empty:
                    st.plotly_chart(px.bar(th, x="complaints", y="theme", orientation="h", text_auto=True,
                                           title="Top complaint themes (negative reviews)")
                                    .update_yaxes(autorange="reversed"), use_container_width=True)
                st.caption("Method: Portuguese sentiment lexicon (with negation) + star rating; themes via keyword groups.")
                if st.button("🤖 Gemini: summarise complaints into actions"):
                    from src.ai import insights
                    samples_f = P / "negative_review_samples.json"
                    samples = json.loads(samples_f.read_text(encoding="utf-8")) if samples_f.exists() else []
                    with st.spinner("Gemini is reading negative reviews..."):
                        try:
                            st.markdown(insights.summarize_complaints(samples, th.to_dict("records")))
                        except Exception as e:
                            st.warning(f"Gemini unavailable right now ({str(e)[:120]}). Try again in a few minutes.")

# ---------------------------------------------------------------- What-if
with T["🧪 What-if"]:
    if not _fallback("🧪 What-if"):
        with guard("🧪 What-if"):
            st.subheader("🧪 What-if: reduce late deliveries")
            base = S.get("what_if_baseline")
            if not base:
                st.info("What-if simulator not available for this dataset.")
            else:
                from src import advanced
                red = st.slider("Reduce late deliveries by (%)", 0, 100, 50, step=5)
                r = advanced.simulate(base, red)
                c = st.columns(4)
                c[0].metric("Late deliveries", f"{r['late_pct'][1]:.1f}%", f"{r['late_pct'][1]-r['late_pct'][0]:+.1f} pp",
                            delta_color="inverse")
                c[1].metric("Avg review", f"{r['avg_review'][1]:.2f} ★", f"{r['avg_review'][1]-r['avg_review'][0]:+.2f}")
                c[2].metric("Negative reviews", f"{r['negative_review_pct'][1]:.1f}%",
                            f"{r['negative_review_pct'][1]-r['negative_review_pct'][0]:+.1f} pp", delta_color="inverse")
                c[3].metric("Repeat rate", f"{r['repeat_rate_pct'][1]:.2f}%",
                            f"{r['repeat_rate_pct'][1]-r['repeat_rate_pct'][0]:+.2f} pp")
                st.success(f"≈ **{max(r['fewer_negative_reviews'], 0):,.0f} fewer negative reviews** and "
                           f"≈ **{max(r['extra_repeat_customers'], 0):,.0f} extra repeat customers** "
                           f"(≈ {brl(max(r['extra_revenue'], 0))} extra revenue).")
                st.caption(f"Based on observed data: late orders average {base['review_late']:.2f}★ vs "
                           f"{base['review_ontime']:.2f}★ on-time; repeat rate {base['repeat_late_pct']:.2f}% vs "
                           f"{base['repeat_ontime_pct']:.2f}% when the first order was late vs on-time. "
                           "Simple mix model -- shows direction & size, not a causal guarantee.")

# ---------------------------------------------------------------- AI Chatbot
with T["💬 AI Chatbot"]:
    if not _fallback("💬 AI Chatbot"):
        with guard("💬 AI Chatbot"):
            st.subheader(f"💬 AI Chatbot -- {META.get('dataset', 'Olist')}")
            st.caption("Data ke baare mein kuch bhi poochho (English ya Hinglish). "
                       "Example: *Top 5 states by revenue in 2018* · *Churn kya hai?* · *Revenue badhane ke 3 tips do*")
            if "chat" not in st.session_state:
                st.session_state.chat = [{"role": "assistant",
                                          "content": "Namaste! 👋 Main aapka Data AI hoon. Sales, customers, delivery, "
                                                     "reviews -- kuch bhi poochho."}]
            c1, c2 = st.columns([6, 1])
            if c2.button("🗑️ Clear chat"):
                st.session_state.chat = st.session_state.chat[:1]
            box = st.container(height=520)
            for i, m in enumerate(st.session_state.chat):
                with box.chat_message(m["role"]):
                    st.markdown(m["content"])
                    if m.get("data") is not None:
                        st.dataframe(m["data"], use_container_width=True, hide_index=True)
                    if m.get("sql"):
                        with st.expander("SQL dekho"):
                            st.code(m["sql"], language="sql")
            prompt = st.chat_input("Apna sawaal likho...")
            if prompt:
                st.session_state.chat.append({"role": "user", "content": prompt})
                with box.chat_message("user"):
                    st.markdown(prompt)
                with box.chat_message("assistant"):
                    with st.spinner("Soch raha hoon..."):
                        from src.ai import chatbot
                        hist = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat[:-1]]
                        try:
                            r = chatbot.reply(prompt, hist)
                        except Exception as e:
                            r = {"text": f"Sorry, error aaya: {str(e)[:200]}", "sql": None, "data": None}
                    st.markdown(r["text"])
                    if r["data"] is not None:
                        st.dataframe(r["data"], use_container_width=True, hide_index=True)
                    if r["sql"]:
                        with st.expander("SQL dekho"):
                            st.code(r["sql"], language="sql")
                st.session_state.chat.append({"role": "assistant", "content": r["text"], "sql": r["sql"], "data": r["data"]})

# ---------------------------------------------------------------- AI Analyst
with T["🤖 AI Analyst"]:
    if not _fallback("🤖 AI Analyst"):
        with guard("🤖 AI Analyst"):
            if not config.GEMINI_API_KEY:
                st.warning("Add GEMINI_API_KEY to env.txt (or Streamlit secrets) to enable the AI Analyst.")
            st.subheader("💬 Ask your data (Natural Language → SQL)")
            examples = ["Top 5 states by revenue in 2018", "Which categories have the worst average review?",
                        "Monthly order count trend for 2017", "Average delivery days for late vs on-time orders"]
            q = st.text_input("Question", placeholder=examples[0])
            st.caption("Try: " + " · ".join(examples))
            if st.button("Ask", type="primary") and q:
                from src.ai import nl2sql
                with st.spinner("Gemini is writing SQL..."):
                    try:
                        res = nl2sql.ask(q)
                    except Exception as e:
                        res = {"error": str(e), "sql": None, "data": None}
                if res.get("sql"):
                    st.code(res["sql"], language="sql")
                if res.get("error"):
                    st.error(res["error"])
                else:
                    st.dataframe(res["data"], use_container_width=True)
                    st.markdown(res["answer"])
            st.divider()
            st.subheader("📄 AI Executive Report")
            if st.button("Generate report"):
                from src.ai import insights
                from src.report import markdown_to_html, offline_report
                with st.spinner("Writing report..."):
                    try:
                        path = insights.generate_report(S)
                        md = Path(path).read_text(encoding="utf-8")
                    except Exception as e:
                        st.warning(f"Gemini unavailable ({str(e)[:100]}...) -- generated a standard (non-AI) report instead.")
                        md = offline_report(S)
                st.markdown(md)
                st.download_button("⬇️ Download report (HTML → open → Ctrl+P → Save as PDF)",
                                   markdown_to_html(md, "Olist Business Intelligence Report"),
                                   "olist_business_report.html", mime="text/html")
                st.download_button("Download report (.md)", md, "olist_business_report.md")

"""Upload ANY dataset -> automatic analysis.

load -> clean -> profile -> KPIs -> insights (rule-based) -> charts spec -> AI Q&A (Gemini NL->SQL on the file)
Works for CSV, TSV, Excel (.xlsx/.xls, needs openpyxl), JSON and Parquet.
"""
import io
import warnings
import re
import sqlite3

import numpy as np
import pandas as pd

MONEY_WORDS = ("revenue", "sales", "amount", "price", "total", "value", "profit", "cost", "income", "payment",
               "spend", "salary", "fare", "gmv", "turnover")
ID_WORDS = ("id", "code", "uuid", "key", "zip", "pin", "phone", "mobile")


# ---------------------------------------------------------------- Load
def load_file(data: bytes, name: str) -> pd.DataFrame:
    n = name.lower()
    if n.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            return pd.read_excel(io.BytesIO(data))
        except ImportError as e:
            raise ImportError("Excel files need the 'openpyxl' package (pip install openpyxl) -- "
                              "or save the sheet as CSV and upload that.") from e
    if n.endswith(".json"):
        try:
            return pd.read_json(io.BytesIO(data))
        except ValueError:
            return pd.read_json(io.BytesIO(data), lines=True)
    if n.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(data))
    # CSV / TSV / TXT: try encodings and let pandas sniff the separator
    last = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding=enc)
            if df.shape[1] == 1 and ";" in str(df.columns[0]):
                df = pd.read_csv(io.BytesIO(data), sep=";", encoding=enc)
            return df
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last = e
    raise ValueError(f"Could not read file: {last}")


# ---------------------------------------------------------------- Clean
def _snake(c: str) -> str:
    c = re.sub(r"[^0-9a-zA-Z]+", "_", str(c).strip()).strip("_").lower()
    return c or "column"


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    log = []
    d = df.copy()
    new_cols, seen = [], {}
    for c in d.columns:
        s = _snake(c)
        seen[s] = seen.get(s, 0) + 1
        new_cols.append(s if seen[s] == 1 else f"{s}_{seen[s]}")
    if list(d.columns) != new_cols:
        log.append("Renamed columns to clean snake_case names")
    d.columns = new_cols

    empty_cols = [c for c in d.columns if d[c].isna().all()]
    if empty_cols:
        d = d.drop(columns=empty_cols)
        log.append(f"Dropped {len(empty_cols)} completely empty column(s): {', '.join(empty_cols[:5])}")
    before = len(d)
    d = d.dropna(how="all")
    if len(d) < before:
        log.append(f"Dropped {before - len(d):,} completely empty row(s)")
    dups = int(d.duplicated().sum())
    if dups:
        d = d.drop_duplicates()
        log.append(f"Removed {dups:,} duplicate row(s)")

    for c in d.columns:
        if not (pd.api.types.is_object_dtype(d[c]) or pd.api.types.is_string_dtype(d[c])):
            continue
        s = d[c].astype("string").str.strip()
        d[c] = s.replace({"": pd.NA, "nan": pd.NA, "NaN": pd.NA, "null": pd.NA, "NULL": pd.NA, "None": pd.NA,
                          "N/A": pd.NA, "NA": pd.NA, "-": pd.NA})
        nonnull = d[c].dropna()
        if nonnull.empty:
            continue
        # dates stored as text (checked BEFORE numbers so 01/02/2023 is not turned into 1022023)
        datey = nonnull.str.match(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}").mean() > 0.8
        if datey or any(w in c for w in ("date", "time", "_at", "timestamp", "period")):
            best = None
            for dayfirst in (False, True):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    dt = pd.to_datetime(d[c], errors="coerce", dayfirst=dayfirst)
                if best is None or dt.notna().sum() > best.notna().sum():
                    best = dt
            if best.notna().sum() >= 0.8 * nonnull.size:
                d[c] = best
                log.append(f"Converted '{c}' to date/time")
                continue
        # decimal comma (Brazil/Europe): "10,5" / "1.234,56" -> 10.5 / 1234.56
        if nonnull.str.fullmatch(r"-?[\d.]*\d,\d+").mean() > 0.6:
            nonnull = nonnull.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            d[c] = d[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        # numbers stored as text: "1,234.50", "R$ 99", "₹ 2,500", "45%"  (but NOT codes like "S12" / "ORD-001")
        stripped = nonnull.str.replace(r"(?i)\b(R\$|Rs\.?|INR|USD|EUR|GBP)|[$€£₹¥%,\s]", "", regex=True)
        is_num = stripped.str.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
        if is_num.mean() > 0.95 and not any(w in c for w in ID_WORDS):
            d[c] = pd.to_numeric(d[c].str.replace(r"(?i)\b(R\$|Rs\.?|INR|USD|EUR|GBP)|[$€£₹¥%,\s]", "", regex=True),
                                 errors="coerce").astype("float64")
            log.append(f"Converted '{c}' from text to number")
    for c in d.columns:  # nullable pandas dtypes -> plain numpy dtypes (plays nicer with charts/corr)
        if str(d[c].dtype) in ("Int64", "Float64", "Int32", "Float32"):
            d[c] = d[c].astype("float64")
        elif str(d[c].dtype) == "string":
            d[c] = d[c].astype(object)
    if not log:
        log.append("Data was already clean -- no changes needed")
    return d.reset_index(drop=True), log


# ---------------------------------------------------------------- Profile
def column_role(s: pd.Series, name: str) -> str:
    n = s.notna().sum()
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    if pd.api.types.is_bool_dtype(s):
        return "category"
    uniq = s.nunique(dropna=True)
    if pd.api.types.is_numeric_dtype(s):
        if (any(name == w or name.endswith("_" + w) or name.startswith(w + "_") for w in ID_WORDS)
                and uniq > 0.9 * max(n, 1)):
            return "id"
        countish = any(w in name for w in ("qty", "quantity", "count", "units", "amount", "num", "price", "total"))
        return "category" if uniq <= 12 and n > 50 and not countish else "numeric"
    if uniq > 0.9 * max(n, 1) and n > 50:
        avg_len = s.dropna().astype(str).str.len().mean()
        return "text" if avg_len > 40 else "id"
    avg_len = s.dropna().astype(str).str.len().mean() if n else 0
    return "text" if avg_len > 60 else "category"


def profile(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = df[c]
        role = column_role(s, c)
        r = {"column": c, "role": role, "dtype": str(s.dtype), "missing_pct": round(s.isna().mean() * 100, 2),
             "unique": int(s.nunique(dropna=True)), "example": str(s.dropna().iloc[0])[:40] if s.notna().any() else ""}
        if role == "numeric":
            x = s.dropna()
            q1, q3 = x.quantile([.25, .75])
            iqr = q3 - q1
            r.update(mean=round(float(x.mean()), 3), median=round(float(x.median()), 3), min=float(x.min()),
                     max=float(x.max()),
                     outliers_pct=round(float(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).mean() * 100), 2))
        rows.append(r)
    return pd.DataFrame(rows)


def roles(prof: pd.DataFrame) -> dict[str, list[str]]:
    return {r: prof.loc[prof["role"] == r, "column"].tolist() for r in ("numeric", "category", "date", "text", "id")}


def main_measure(df: pd.DataFrame, numeric: list[str]) -> str | None:
    for w in MONEY_WORDS:
        for c in numeric:
            if w in c:
                return c
    return max(numeric, key=lambda c: df[c].sum(), default=None) if numeric else None


# ---------------------------------------------------------------- KPIs & insights
def kpis(df: pd.DataFrame, r: dict) -> list[tuple[str, str]]:
    out = [("Rows", f"{len(df):,}"), ("Columns", f"{df.shape[1]}"),
           ("Missing cells", f"{df.isna().mean().mean() * 100:.1f}%")]
    m = main_measure(df, r["numeric"])
    if m:
        out += [(f"Total {m}", f"{df[m].sum():,.2f}"), (f"Avg {m}", f"{df[m].mean():,.2f}")]
    if r["date"]:
        d = df[r["date"][0]].dropna()
        if len(d):
            out.append(("Date range", f"{d.min():%d %b %Y} → {d.max():%d %b %Y}"))
    return out


def insights(df: pd.DataFrame, prof: pd.DataFrame) -> list[str]:
    r = roles(prof)
    out = []
    m = main_measure(df, r["numeric"])
    # top category by measure (or by count)
    for cat in r["category"][:3]:
        if m:
            g = df.groupby(cat, observed=True)[m].sum().sort_values(ascending=False)
            if len(g) > 1 and g.sum():
                out.append(f"**{g.index[0]}** is the top `{cat}` by `{m}` ({g.iloc[0] / g.sum() * 100:.1f}% of total).")
        else:
            vc = df[cat].value_counts(normalize=True)
            if len(vc) > 1:
                out.append(f"Most common `{cat}`: **{vc.index[0]}** ({vc.iloc[0] * 100:.1f}% of rows).")
    # trend (by main measure, or by row count when there is no measure)
    if r["date"]:
        dcol = r["date"][0]
        base = df.set_index(dcol)[m] if m else df.set_index(dcol).assign(_rows=1)["_rows"]
        label = m or "rows"
        t = base[base.index.notna()].resample("MS").sum()
        t = t[t >= t.median() * 0.05]          # ignore near-empty edge months
        t = t[t != 0]
        if len(t) >= 3:
            first, last = t.iloc[: max(1, len(t) // 4)].mean(), t.iloc[-max(1, len(t) // 4):].mean()
            if first:
                out.append(f"`{label}` per month moved **{(last / first - 1) * 100:+.0f}%** from the start to the end of "
                           f"the period; best month **{t.idxmax():%b %Y}**.")
    # correlations
    num = [c for c in r["numeric"] if df[c].nunique() > 2]
    if len(num) >= 2:
        cm = df[num].corr(numeric_only=True).abs().to_numpy(copy=True)
        np.fill_diagonal(cm, 0)
        if np.all(np.isnan(cm)):
            return out or ["No strong patterns detected automatically -- try the AI questions below."]
        a, b = np.unravel_index(np.nanargmax(cm), cm.shape)
        val = df[num].corr().iloc[a, b]
        if abs(val) >= 0.3:
            out.append(f"`{num[a]}` and `{num[b]}` are {'positively' if val > 0 else 'negatively'} correlated "
                       f"(r = {val:.2f}).")
    # data quality
    miss = prof[prof["missing_pct"] > 20]
    if len(miss):
        out.append("⚠️ High missing values in: " + ", ".join(f"`{c}` ({p:.0f}%)" for c, p in
                                                            zip(miss["column"], miss["missing_pct"])) + ".")
    outl = prof[prof.get("outliers_pct", pd.Series(dtype=float)).fillna(0) > 5] if "outliers_pct" in prof else []
    if len(outl):
        out.append("⚠️ Many outliers in: " + ", ".join(f"`{c}`" for c in outl["column"]) + " -- check for errors.")
    return out or ["No strong patterns detected automatically -- try the AI questions below."]


# ---------------------------------------------------------------- AI Q&A on the uploaded file
SQL_SYSTEM = """You write SQLite SQL for a single table named `data`.
Columns (name: type, example):
{schema}
Rules: return ONLY one SELECT statement, no markdown. Use only these columns. Add LIMIT 200 unless a single value
is asked. Dates are stored as text 'YYYY-MM-DD HH:MM:SS' -- use strftime() for month/year."""


def to_sqlite(df: pd.DataFrame) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", check_same_thread=False)
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    out.to_sql("data", con, index=False)
    return con


def ask(question: str, df: pd.DataFrame, con: sqlite3.Connection) -> dict:
    from src.ai.gemini_client import generate
    from src.ai.nl2sql import clean_sql, validate_sql
    schema = "\n".join(f"- {c}: {df[c].dtype}, e.g. {str(df[c].dropna().iloc[0])[:30] if df[c].notna().any() else ''}"
                       for c in df.columns)
    sql = clean_sql(generate(question, system=SQL_SYSTEM.format(schema=schema), temperature=0.0))
    safe = validate_sql(sql, limit=200)
    try:
        res = pd.read_sql(safe, con)
    except Exception as e:  # one self-correction round
        sql = clean_sql(generate(f"Query failed: {e}\nQuery:\n{sql}\nReturn ONLY corrected SQLite SQL.",
                                 system=SQL_SYSTEM.format(schema=schema), temperature=0.0))
        safe = validate_sql(sql, limit=200)
        res = pd.read_sql(safe, con)
    try:
        answer = generate(f"Question: {question}\nResult:\n{res.head(30).to_csv(index=False)}\n"
                          "Answer in 2-4 short bullets with the actual numbers. Do not invent numbers.",
                          system="You are a concise data analyst.")
    except Exception:
        answer = None
    return {"sql": safe, "data": res, "answer": answer}


def ai_summary(df: pd.DataFrame, prof: pd.DataFrame, rule_insights: list[str], file_name: str) -> str:
    from src.ai.gemini_client import generate
    prompt = (f"Dataset '{file_name}': {len(df):,} rows x {df.shape[1]} columns.\nColumn profile:\n"
              f"{prof.to_csv(index=False)[:5000]}\nSample rows:\n{df.head(8).to_csv(index=False)[:2500]}\n"
              f"Automatic findings:\n- " + "\n- ".join(rule_insights) +
              "\n\nAs a senior data analyst write: 1) What this dataset is about (1 line), 2) 4 key insights, "
              "3) 3 recommended analyses or business actions, 4) data quality issues to fix. Max 18 lines, markdown.")
    return generate(prompt, system="You are a senior data analyst. Use only facts from the provided profile.")


def markdown_report(file_name: str, df: pd.DataFrame, prof: pd.DataFrame, log: list[str], ins: list[str],
                    ai_text: str | None = None) -> str:
    r = roles(prof)
    lines = [f"# Data Analysis Report: {file_name}", "",
             f"- Rows: **{len(df):,}** · Columns: **{df.shape[1]}**",
             f"- Numeric: {len(r['numeric'])} · Categorical: {len(r['category'])} · Date: {len(r['date'])} · "
             f"Text: {len(r['text'])} · ID: {len(r['id'])}", "", "## Cleaning steps"]
    lines += [f"- {x}" for x in log]
    lines += ["", "## Key insights"] + [f"- {x}" for x in ins]
    if ai_text:
        lines += ["", "## AI analysis", ai_text]
    lines += ["", "## Column profile", "| Column | Role | Missing % | Unique | Example |", "|---|---|---|---|---|"]
    for _, p in prof.iterrows():
        lines.append(f"| {p['column']} | {p['role']} | {p['missing_pct']} | {p['unique']} | {p['example']} |")
    return "\n".join(lines)

"""Generate a Power BI Project (PBIP: TMDL semantic model + PBIR report) for the Olist dashboard.

  python powerbi/build_pbip.py  -> powerbi/Olist_Dashboard/Olist_Dashboard.pbip

Open the .pbip in Power BI Desktop, click Refresh (data loads from data/processed CSVs), then
File > Save as .pbix if you want a single file.
"""
import json
import shutil
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "Olist_Dashboard"
NAME = "Olist_Dashboard"
DATA_FOLDER = r"E:\olist-intelligence\data\processed" + "\\"
LAYOUT = json.loads((HERE / "backgrounds" / "layout_positions.json").read_text())
EXCL = 'NOT fact_orders[order_status] IN {"canceled", "unavailable"}'
EXCL_I = 'NOT fact_order_items[order_status] IN {"canceled", "unavailable"}'

# ------------------------------------------------------------------ semantic model
# table -> (csv file, [(column, tmdl dataType, M type, extra props)], extra M steps)
T = "text"
TABLES = {
    "fact_orders": ("fact_orders", [
        ("order_id", "string", T), ("customer_unique_id", "string", T), ("order_status", "string", T),
        ("purchase_date", "dateTime", "date"), ("date_key", "int64", "Int64.Type"),
        ("delivery_days", "double", "number"), ("delay_days", "double", "number"), ("is_late", "double", "number"),
        ("product_revenue", "double", "number"), ("freight_value", "double", "number"),
        ("gmv", "double", "number"), ("payment_value", "double", "number"), ("payment_type", "string", T),
        ("review_score", "double", "number"), ("est_gross_profit", "double", "number"),
        ("customer_state", "string", T)]),
    "fact_order_items": ("fact_order_items", [
        ("order_id", "string", T), ("order_item_id", "int64", "Int64.Type"), ("product_id", "string", T),
        ("seller_id", "string", T), ("price", "double", "number"), ("freight_value", "double", "number"),
        ("category", "string", T), ("est_gross_profit", "double", "number"), ("order_status", "string", T)]),
    "dim_customer": ("dim_customer", [("customer_unique_id", "string", T), ("city", "string", T),
                                      ("state", "string", T)]),
    "dim_product": ("dim_product", [("product_id", "string", T), ("category", "string", T)]),
    "dim_seller": ("dim_seller", [("seller_id", "string", T), ("state", "string", T)]),
    "dim_date": ("dim_date", [("date", "dateTime", "date"), ("date_key", "int64", "Int64.Type"),
                              ("year", "int64", "Int64.Type"), ("quarter", "int64", "Int64.Type"),
                              ("month", "int64", "Int64.Type"), ("month_name", "string", T),
                              ("year_month", "string", T), ("day_name", "string", T)]),
    "customer_rfm": ("customer_rfm", [("customer_unique_id", "string", T), ("frequency", "int64", "Int64.Type"),
                                      ("monetary", "double", "number"), ("recency_days", "int64", "Int64.Type"),
                                      ("segment", "string", T), ("recommended_action", "string", T)]),
    "customer_clv": ("customer_clv", [("customer_unique_id", "string", T), ("total_clv", "double", "number"),
                                      ("clv_tier", "string", T)]),
    "agg_cohort_retention": ("agg_cohort_retention", [("cohort_month", "string", T),
                                                      ("month_number", "int64", "Int64.Type"),
                                                      ("retention_pct", "double", "number")]),
    "churn_feature_importance": ("churn_feature_importance", [("feature", "string", T),
                                                              ("importance", "double", "number")]),
    "agg_revenue_anomalies": ("agg_revenue_anomalies", [("week", "dateTime", "date"), ("revenue", "double", "number"),
                                                        ("expected", "double", "number"),
                                                        ("change_pct", "double", "number"), ("alert", "string", T)]),
    "agg_category": ("agg_category", [("category", "string", T), ("revenue", "double", "number"),
                                      ("avg_price", "double", "number"), ("avg_review", "double", "number"),
                                      ("revenue_share_pct", "double", "number"),
                                      ("cumulative_share_pct", "double", "number")]),
    "agg_seller_scorecard": ("agg_seller_scorecard", [("seller_id", "string", T), ("state", "string", T),
                                                      ("revenue", "double", "number"), ("orders", "int64", "Int64.Type"),
                                                      ("avg_review", "double", "number"),
                                                      ("late_pct", "double", "number"), ("score", "double", "number"),
                                                      ("tier", "string", T)]),
    "review_sentiment": ("review_sentiment", [("order_id", "string", T), ("sentiment", "string", T)]),
    "agg_complaint_themes": ("agg_complaint_themes", [("theme", "string", T), ("complaints", "int64", "Int64.Type")]),
    "agg_sentiment_month": ("agg_sentiment_month", [("review_month", "string", T),
                                                    ("positive_pct", "double", "number"),
                                                    ("neutral_pct", "double", "number"),
                                                    ("negative_pct", "double", "number")]),
    "agg_state": ("agg_state", [("state", "string", T), ("revenue", "double", "number"),
                                ("avg_delivery_days", "double", "number"), ("late_pct", "double", "number"),
                                ("avg_review", "double", "number")]),
}
EXTRA_M = {  # extra Power Query steps (applied after typing)
    "dim_date": ('#"Day Num" = Table.AddColumn(Typed, "day_num", each Date.DayOfWeek([date], Day.Monday) + 1, '
                 'Int64.Type)', '#"Day Num"'),
    "agg_sentiment_month": ('Recent = Table.SelectRows(Typed, each [review_month] >= "2017-01")', "Recent"),
    "agg_revenue_anomalies": ('Alerts = Table.SelectRows(Typed, each [alert] <> null and [alert] <> "")', "Alerts"),
}
EXTRA_COLS = {"dim_date": [("day_num", "int64")]}
SORT_BY = {("dim_date", "day_name"): "day_num", ("dim_date", "month_name"): "month"}

MEASURES = {  # table -> [(name, expression, formatString)]
    "fact_orders": [
        ("Revenue", f"CALCULATE ( SUM ( fact_orders[product_revenue] ), {EXCL} )", r'\R$ #,0'),
        ("Est Gross Profit", f"CALCULATE ( SUM ( fact_orders[est_gross_profit] ), {EXCL} )", r'\R$ #,0'),
        ("Orders", f"CALCULATE ( DISTINCTCOUNT ( fact_orders[order_id] ), {EXCL} )", "#,0"),
        ("Customers", f"CALCULATE ( DISTINCTCOUNT ( fact_orders[customer_unique_id] ), {EXCL} )", "#,0"),
        ("AOV", "DIVIDE ( [Revenue], [Orders] )", r'\R$ #,0'),
        ("Avg Review", "AVERAGE ( fact_orders[review_score] )", "0.00"),
        ("Revenue 3M Avg", "DIVIDE ( CALCULATE ( [Revenue], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), "
                           "-3, MONTH ) ), 3 )", r'\R$ #,0'),
        ("Top10 State Revenue", "IF ( RANKX ( ALL ( fact_orders[customer_state] ), [Revenue],, DESC ) <= 10, "
                                "[Revenue] )", r'\R$ #,0'),
        ("Repeat Rate %", "DIVIDE ( COUNTROWS ( FILTER ( VALUES ( fact_orders[customer_unique_id] ), "
                          "CALCULATE ( DISTINCTCOUNT ( fact_orders[order_id] ) ) > 1 ) ), [Customers] )", "0.0%"),
        ("Revenue YTD", "TOTALYTD ( [Revenue], dim_date[date] )", r'\R$ #,0'),
        ("YoY Growth %", "VAR cur = [Revenue YTD] VAR prev = CALCULATE ( [Revenue YTD], SAMEPERIODLASTYEAR "
                         "( dim_date[date] ) ) RETURN DIVIDE ( cur - prev, prev )", "+0.0%;-0.0%"),
        ("Avg Delivery Days", "AVERAGE ( fact_orders[delivery_days] )", "0.0"),
        ("Late Delivery %", "AVERAGE ( fact_orders[is_late] )", "0.0%"),
        ("Negative Review %", "DIVIDE ( CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[review_score] <= 2 ), "
                              "CALCULATE ( COUNTROWS ( fact_orders ), NOT ISBLANK ( fact_orders[review_score] ) ) )",
         "0.0%"),
        ("Forecast MAPE", "0.149", "0.0%"),
        ("Bucket Avg Review", "IF ( ISBLANK ( SELECTEDVALUE ( fact_orders[Delivery Bucket] ) ), BLANK (), "
                              "[Avg Review] )", "0.00"),
        ("Bucket Negative %", "IF ( ISBLANK ( SELECTEDVALUE ( fact_orders[Delivery Bucket] ) ), BLANK (), "
                              "[Negative Review %] )", "0.0%"),
    ],
    "fact_order_items": [
        ("Item Revenue", f"CALCULATE ( SUM ( fact_order_items[price] ), {EXCL_I} )", r'\R$ #,0'),
        ("Top10 Category Revenue", "IF ( RANKX ( ALL ( dim_product[category] ), [Item Revenue],, DESC ) <= 10, "
                                   "[Item Revenue] )", r'\R$ #,0'),
    ],
    "customer_rfm": [
        ("RFM Customers", "COUNTROWS ( customer_rfm )", "#,0"),
        ("RFM Revenue", "SUM ( customer_rfm[monetary] )", r'\R$ #,0'),
        ("At Risk Customers", 'CALCULATE ( COUNTROWS ( customer_rfm ), customer_rfm[segment] = "At Risk" )', "#,0"),
    ],
    "customer_clv": [("Avg CLV", "AVERAGE ( customer_clv[total_clv] )", r'\R$ #,0')],
    "agg_cohort_retention": [
        ("Retention %", "DIVIDE ( AVERAGE ( agg_cohort_retention[retention_pct] ), 100 )", "0.0%"),
        ("Month1 Retention %", "DIVIDE ( CALCULATE ( AVERAGE ( agg_cohort_retention[retention_pct] ), "
                               "agg_cohort_retention[month_number] = 1 ), 100 )", "0.00%"),
    ],
    "churn_feature_importance": [("Churn Driver Importance", "SUM ( churn_feature_importance[importance] )",
                                  "0.000")],
    "forecast_chart": [
        ("Actual Revenue", "SUM ( forecast_chart[actual] )", r'\R$ #,0'),
        ("Forecast Revenue", "SUM ( forecast_chart[forecast] )", r'\R$ #,0'),
        ("Forecast Lower", "SUM ( forecast_chart[lower] )", r'\R$ #,0'),
        ("Forecast Upper", "SUM ( forecast_chart[upper] )", r'\R$ #,0'),
        ("Avg Weekly Revenue", "AVERAGE ( forecast_chart[actual] )", r'\R$ #,0'),
        ("Forecast Next 12W", "SUM ( forecast_chart[forecast] )", r'\R$ #,0'),
    ],
    "agg_category": [
        ("Category Revenue", "SUM ( agg_category[revenue] )", r'\R$ #,0'),
        ("Cumulative Share %", "DIVIDE ( MAX ( agg_category[cumulative_share_pct] ), 100 )", "0%"),
        ("Avg Category Price", "AVERAGE ( agg_category[avg_price] )", r'\R$ #,0'),
        ("Avg Category Review", "AVERAGE ( agg_category[avg_review] )", "0.00"),
        ("Category Count", "DISTINCTCOUNT ( agg_category[category] )", "#,0"),
        ("Top Category Share %", "DIVIDE ( MAX ( agg_category[revenue_share_pct] ), 100 )", "0.0%"),
    ],
    "agg_seller_scorecard": [
        ("Seller Count", "COUNTROWS ( agg_seller_scorecard )", "#,0"),
        ("Top Sellers", 'CALCULATE ( COUNTROWS ( agg_seller_scorecard ), agg_seller_scorecard[tier] = '
                        '"Top Seller" )', "#,0"),
        ("Avg Seller Score", "AVERAGE ( agg_seller_scorecard[score] )", "0.0"),
    ],
    "review_sentiment": [
        ("Positive Sentiment %", 'DIVIDE ( CALCULATE ( COUNTROWS ( review_sentiment ), review_sentiment[sentiment] = '
                                 '"positive" ), COUNTROWS ( review_sentiment ) )', "0.0%")],
    "agg_complaint_themes": [("Total Complaints", "SUM ( agg_complaint_themes[complaints] )", "#,0")],
    "agg_sentiment_month": [
        ("Positive %", "DIVIDE ( SUM ( agg_sentiment_month[positive_pct] ), 100 )", "0%"),
        ("Neutral %", "DIVIDE ( SUM ( agg_sentiment_month[neutral_pct] ), 100 )", "0%"),
        ("Negative %", "DIVIDE ( SUM ( agg_sentiment_month[negative_pct] ), 100 )", "0%"),
    ],
    "agg_state": [("State Delivery Days", "AVERAGE ( agg_state[avg_delivery_days] )", "0.0")],
}
CALC_COLS = {"fact_orders": [("Delivery Bucket", 'SWITCH ( TRUE (), ISBLANK ( fact_orders[delay_days] ), BLANK (), '
                                                 'fact_orders[delay_days] <= -10, "1. 10+ days early", '
                                                 'fact_orders[delay_days] <= 0, "2. On time", '
                                                 'fact_orders[delay_days] <= 7, "3. 1-7 days late", '
                                                 '"4. 7+ days late" )')]}
RELATIONSHIPS = [  # (from table, from col, to table, to col, both directions?)
    ("fact_orders", "date_key", "dim_date", "date_key", False),
    ("fact_orders", "customer_unique_id", "dim_customer", "customer_unique_id", False),
    ("fact_order_items", "order_id", "fact_orders", "order_id", True),
    ("fact_order_items", "product_id", "dim_product", "product_id", False),
    ("fact_order_items", "seller_id", "dim_seller", "seller_id", False),
    ("customer_rfm", "customer_unique_id", "dim_customer", "customer_unique_id", False),
    ("customer_clv", "customer_unique_id", "dim_customer", "customer_unique_id", False),
    ("review_sentiment", "order_id", "fact_orders", "order_id", False),
]


def q(name: str) -> str:
    return f"'{name}'" if any(ch in name for ch in " %-") else name


def m_csv(file: str, cols) -> str:
    mt = {"text": "type text", "number": "type number", "date": "type date", "Int64.Type": "Int64.Type"}
    types = ", ".join(f'{{"{c}", {mt[t]}}}' for c, _, t in cols)
    keep = ", ".join(f'"{c}"' for c, _, _ in cols)
    return (f'let\n    Source = Csv.Document(File.Contents(DataFolder & "{file}.csv"), [Delimiter = ",", '
            f'Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
            f'    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n'
            f'    Kept = Table.SelectColumns(Promoted, {{{keep}}}),\n'
            f'    Typed = Table.TransformColumnTypes(Kept, {{{types}}}, "en-US")')


def table_tmdl(name: str, file: str, cols) -> str:
    L = [f"table {name}"]
    if name == "dim_date":
        L.append("\tdataCategory: Time")
    L.append("")
    for mname, expr, fmt in MEASURES.get(name, []):
        L += [f"\tmeasure {q(mname)} = {expr}", f"\t\tformatString: {fmt}", ""]
    for c, dt, _ in cols:
        L.append(f"\tcolumn {c}")
        L.append(f"\t\tdataType: {dt}")
        if name == "dim_date" and c == "date":
            L.append("\t\tisKey")
            L.append("\t\tformatString: dd-mmm-yyyy")
        elif dt == "dateTime":
            L.append("\t\tformatString: dd-mmm-yyyy")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {c}")
        if (name, c) in SORT_BY:
            L.append(f"\t\tsortByColumn: {SORT_BY[(name, c)]}")
        L.append("")
    for c, dt in EXTRA_COLS.get(name, []):
        L += [f"\tcolumn {c}", f"\t\tdataType: {dt}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {c}", ""]
    for cname, expr in CALC_COLS.get(name, []):
        L += [f"\tcolumn {q(cname)} = {expr}", "\t\tdataType: string", "\t\tsummarizeBy: none", ""]
    m = m_csv(file, cols)
    last = "Typed"
    if name in EXTRA_M:
        step, last = EXTRA_M[name]
        m += f",\n    {step}"
    m += f"\nin\n    {last}"
    L.append(f"\tpartition {name} = m")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    L += ["\t\t\t\t" + line for line in m.split("\n")]
    L.append("")
    return "\n".join(L) + "\n"


def forecast_table_tmdl() -> str:
    m = ('let\n'
         '    Hist = Csv.Document(File.Contents(DataFolder & "revenue_weekly.csv"), [Delimiter = ",", Encoding = 65001]),\n'
         '    HistP = Table.PromoteHeaders(Hist, [PromoteAllScalars = true]),\n'
         '    HistR = Table.RenameColumns(HistP, {{"revenue", "actual"}}),\n'
         '    Fc = Csv.Document(File.Contents(DataFolder & "forecast_weekly.csv"), [Delimiter = ",", Encoding = 65001]),\n'
         '    FcP = Table.PromoteHeaders(Fc, [PromoteAllScalars = true]),\n'
         '    Combined = Table.Combine({HistR, FcP}),\n'
         '    Typed = Table.TransformColumnTypes(Combined, {{"week", type date}, {"actual", type number}, '
         '{"forecast", type number}, {"lower", type number}, {"upper", type number}}, "en-US")\n'
         'in\n    Typed')
    L = ["table forecast_chart", ""]
    for mname, expr, fmt in MEASURES["forecast_chart"]:
        L += [f"\tmeasure {q(mname)} = {expr}", f"\t\tformatString: {fmt}", ""]
    for c, dt in [("week", "dateTime"), ("actual", "double"), ("forecast", "double"), ("lower", "double"),
                  ("upper", "double")]:
        L += [f"\tcolumn {c}", f"\t\tdataType: {dt}"] + (["\t\tformatString: dd-mmm-yyyy"] if dt == "dateTime" else []) \
             + ["\t\tsummarizeBy: none", f"\t\tsourceColumn: {c}", ""]
    L += ["\tpartition forecast_chart = m", "\t\tmode: import", "\t\tsource ="] + \
         ["\t\t\t\t" + line for line in m.split("\n")] + [""]
    return "\n".join(L) + "\n"


def build_model(root: Path):
    sm = root / f"{NAME}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True)
    (sm / "definition.pbism").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}}, indent=2))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n")
    names = list(TABLES) + ["forecast_chart"]
    (d / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tsourceQueryCulture: en-US\n\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        + "".join(f"ref table {n}\n" for n in names) + "\n")
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery = true, Type = "Text", '
        f'IsParameterQueryRequired = true]\n\n')
    for name, (file, cols) in TABLES.items():
        (d / "tables" / f"{name}.tmdl").write_text(table_tmdl(name, file, cols))
    (d / "tables" / "forecast_chart.tmdl").write_text(forecast_table_tmdl())
    rel = []
    for i, (ft, fc, tt, tc, both) in enumerate(RELATIONSHIPS):
        rel += [f"relationship {uuid.uuid5(uuid.NAMESPACE_DNS, f'{ft}.{fc}.{tt}')}"]
        if both:
            rel.append("\tcrossFilteringBehavior: bothDirections")
        rel += [f"\tfromColumn: {ft}.{fc}", f"\ttoColumn: {tt}.{tc}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel) + "\n")


# ------------------------------------------------------------------ report (PBIR)
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


MEASURE_HOME = {m[0]: t for t, ms in MEASURES.items() for m in ms}
MEASURE_FMT = {m[0]: m[2] for ms in MEASURES.values() for m in ms}


def F(spec: str):
    """'[Measure]' or 'table.column' -> (field, queryRef, nativeRef)"""
    if spec.startswith("["):
        n = spec[1:-1]
        t = MEASURE_HOME[n]
        return mea(t, n), f"{t}.{n}", n
    t, c = spec.split(".", 1)
    return col(t, c), f"{t}.{c}", c


def visual(vtype, roles: dict, x, y, w, h, z=1000, objects=None, sort=None, extra=None):
    qs = {}
    for role, specs in roles.items():
        projs = []
        for s in specs:
            f, qr, nr = F(s)
            projs.append({"field": f, "queryRef": qr, "nativeQueryRef": nr})
        qs[role] = {"projections": projs}
    v = {"visualType": vtype, "query": {"queryState": qs},
         "visualContainerObjects": {
             "title": [{"properties": {"show": lit("false")}}],
             "background": [{"properties": {"show": lit("false")}}],
             "border": [{"properties": {"show": lit("false")}}],
             "dropShadow": [{"properties": {"show": lit("false")}}]},
         "drillFilterOtherVisuals": True}
    if sort:
        f, _, _ = F(sort[0])
        v["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": sort[1]}], "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    out = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
           "name": uuid.uuid4().hex[:20],
           "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}, "visual": v}
    if extra:
        v.update(extra)
    return out


CARD_OBJ = {"categoryLabels": [{"properties": {"show": lit("false")}}],
            "labels": [{"properties": {"fontSize": lit("22D"), "color": {"solid": {"color": lit("'#E5ECF6'")}}}}]}
LEGEND_OFF = {"legend": [{"properties": {"show": lit("false")}}]}
LABELS_ON = {"labels": [{"properties": {"show": lit("true")}}]}

PAGES = [
    ("01_executive.png", "Executive Overview",
     ["[Revenue]", "[Est Gross Profit]", "[Orders]", "[AOV]", "[Avg Review]"],
     [("lineClusteredColumnComboChart", {"Category": ["dim_date.year_month"], "Y": ["[Revenue]"],
                                         "Y2": ["[Revenue 3M Avg]"]}, ("dim_date.year_month", "Ascending"), None),
      ("donutChart", {"Category": ["fact_orders.payment_type"], "Y": ["[Revenue]"]}, None, None),
      ("barChart", {"Category": ["dim_product.category"], "Y": ["[Top10 Category Revenue]"]},
       ("[Top10 Category Revenue]", "Descending"), LEGEND_OFF),
      ("barChart", {"Category": ["fact_orders.customer_state"], "Y": ["[Top10 State Revenue]"]},
       ("[Top10 State Revenue]", "Descending"), LEGEND_OFF),
      ("columnChart", {"Category": ["fact_orders.Delivery Bucket"], "Y": ["[Bucket Avg Review]"]},
       ("fact_orders.Delivery Bucket", "Ascending"), LABELS_ON)]),
    ("02_customers.png", "Customers & RFM",
     ["[Customers]", "[Repeat Rate %]", "[At Risk Customers]", "[Avg CLV]", "[Month1 Retention %]"],
     [("treemap", {"Group": ["customer_rfm.segment"], "Values": ["[RFM Customers]"]}, None, None),
      ("tableEx", {"Values": ["customer_rfm.segment", "[RFM Customers]", "[RFM Revenue]",
                              "customer_rfm.recommended_action"]}, ("[RFM Revenue]", "Descending"), None),
      ("pivotTable", {"Rows": ["agg_cohort_retention.cohort_month"], "Columns": ["agg_cohort_retention.month_number"],
                      "Values": ["[Retention %]"]}, None, None),
      ("barChart", {"Category": ["churn_feature_importance.feature"], "Y": ["[Churn Driver Importance]"]},
       ("[Churn Driver Importance]", "Descending"), LEGEND_OFF)]),
    ("03_sales_forecast.png", "Sales & Forecast",
     ["[Revenue YTD]", "[YoY Growth %]", "[Avg Weekly Revenue]", "[Forecast Next 12W]", "[Forecast MAPE]"],
     [("lineChart", {"Category": ["forecast_chart.week"], "Y": ["[Actual Revenue]", "[Forecast Revenue]", "[Forecast Lower]", "[Forecast Upper]"]},
       ("forecast_chart.week", "Ascending"), None),
      ("columnChart", {"Category": ["dim_date.day_name"], "Y": ["[Revenue]"]}, ("dim_date.day_name", "Ascending"),
       LEGEND_OFF),
      ("lineChart", {"Category": ["dim_date.month_name"], "Series": ["dim_date.year"], "Y": ["[Revenue]"]},
       ("dim_date.month_name", "Ascending"), None),
      ("tableEx", {"Values": ["agg_revenue_anomalies.week", "agg_revenue_anomalies.alert",
                              "agg_revenue_anomalies.revenue", "agg_revenue_anomalies.change_pct"]},
       ("agg_revenue_anomalies.week", "Descending"), None)]),
    ("04_products_sellers.png", "Products & Sellers",
     ["[Category Count]", "[Top Category Share %]", "[Seller Count]", "[Top Sellers]", "[Avg Seller Score]"],
     [("lineClusteredColumnComboChart", {"Category": ["agg_category.category"], "Y": ["[Category Revenue]"],
                                         "Y2": ["[Cumulative Share %]"]}, ("[Category Revenue]", "Descending"), None),
      ("scatterChart", {"Category": ["agg_category.category"], "X": ["[Avg Category Price]"],
                        "Y": ["[Avg Category Review]"], "Size": ["[Category Revenue]"]}, None, LEGEND_OFF),
      ("tableEx", {"Values": ["agg_seller_scorecard.seller_id", "agg_seller_scorecard.state",
                              "agg_seller_scorecard.tier", "agg_seller_scorecard.score",
                              "agg_seller_scorecard.revenue", "agg_seller_scorecard.avg_review",
                              "agg_seller_scorecard.late_pct"]}, ("agg_seller_scorecard.score", "Descending"), None),
      ("donutChart", {"Category": ["agg_seller_scorecard.tier"], "Y": ["[Seller Count]"]}, None, None)]),
    ("05_delivery_reviews.png", "Delivery & Reviews",
     ["[Avg Delivery Days]", "[Late Delivery %]", "[Avg Review]", "[Negative Review %]", "[Positive Sentiment %]"],
     [("columnChart", {"Category": ["fact_orders.Delivery Bucket"], "Y": ["[Bucket Negative %]"]},
       ("fact_orders.Delivery Bucket", "Ascending"), LABELS_ON),
      ("barChart", {"Category": ["agg_state.state"], "Y": ["[State Delivery Days]"]},
       ("[State Delivery Days]", "Descending"), LEGEND_OFF),
      ("barChart", {"Category": ["agg_complaint_themes.theme"], "Y": ["[Total Complaints]"]},
       ("[Total Complaints]", "Descending"), LEGEND_OFF),
      ("lineChart", {"Category": ["agg_sentiment_month.review_month"],
                     "Y": ["[Positive %]", "[Neutral %]", "[Negative %]"]},
       ("agg_sentiment_month.review_month", "Ascending"), None)]),
]
SLICERS = [("dim_date.year", 336, "Year"), ("dim_customer.state", 402, "State"), ("dim_product.category", 468,
                                                                                    "Category")]
NAV_Y = [110, 144, 178, 212, 246]


def build_report(root: Path, theme_path: Path):
    rp = root / f"{NAME}.Report"
    d = rp / "definition"
    reg = rp / "StaticResources" / "RegisteredResources"
    shared = rp / "StaticResources" / "SharedResources" / "BaseThemes"
    for p in (d / "pages", reg, shared):
        p.mkdir(parents=True)
    (rp / "definition.pbir").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    (d / "version.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2))
    shutil.copy(theme_path, shared / "CY24SU10.json")
    shutil.copy(theme_path, reg / "Olist_Dark_Theme.json")
    images = []
    for i, (bg, *_r) in enumerate(PAGES):
        name = f"bg{i + 1:02d}.png"
        shutil.copy(HERE / "backgrounds" / bg, reg / name)
        images.append(name)
    (d / "report.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.59", "type": "SharedResources"},
            "customTheme": {"name": "Olist_Dark_Theme.json", "reportVersionAtImport": "5.59",
                            "type": "RegisteredResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "Olist_Dark_Theme.json", "path": "Olist_Dark_Theme.json", "type": "CustomTheme"}]
                      + [{"name": n, "path": n, "type": "Image"} for n in images]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True,
                     "useDefaultAggregateDisplayName": True}}, indent=2))
    page_ids = [f"page{i + 1:02d}" for i in range(len(PAGES))]
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": page_ids, "activePageName": page_ids[0]}, indent=2))
    for pi, (bg, title, kpis, visuals) in enumerate(PAGES):
        pid = page_ids[pi]
        pd_ = d / "pages" / pid
        (pd_ / "visuals").mkdir(parents=True)
        (pd_ / "page.json").write_text(json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json",
            "name": pid, "displayName": title, "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {
                "background": [{"properties": {
                    "image": {"image": {"name": lit(f"'{images[pi]}'"),
                                        "url": {"expr": {"ResourcePackageItem": {
                                            "PackageName": "RegisteredResources", "PackageType": 1,
                                            "ItemName": images[pi]}}},
                                        "scaling": lit("'Fit'")}},
                    "transparency": lit("0D")}}],
                "outspace": [{"properties": {"color": {"solid": {"color": lit("'#0B1220'")}}}}]}}, indent=2))
        lay = LAYOUT[bg]
        vis = []
        for k, b in zip(kpis, lay["kpis"]):
            money = MEASURE_FMT.get(k[1:-1], "").startswith("\\R$")
            obj = json.loads(json.dumps(CARD_OBJ))
            if money:
                obj["labels"][0]["properties"].update({"labelDisplayUnits": lit("0D"), "labelPrecision": lit("2L")})
            elif "%" not in MEASURE_FMT.get(k[1:-1], ""):
                obj["labels"][0]["properties"]["labelDisplayUnits"] = lit("1D")
            vis.append(visual("card", {"Values": [k]}, b["x"] + 10, b["y"] + 26, b["w"] - 18, b["h"] - 30,
                              objects=obj))
        for (vtype, roles, sort, objs), b in zip(visuals, lay["visuals"]):
            vis.append(visual(vtype, roles, b["x"] + 6, b["y"], b["w"] - 12, b["h"] - 6, objects=objs, sort=sort))
        for spec, y, grp in SLICERS:
            vis.append(visual("slicer", {"Values": [spec]}, 14, y + 15, 182, 40, z=3000,
                              objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}],
                                       "header": [{"properties": {"show": lit("false")}}]},
                              extra={"syncGroup": {"groupName": grp, "fieldChanges": True,
                                                   "filterChanges": True}}))
        for ni, ny in enumerate(NAV_Y):
            if ni == pi:
                continue
            btn = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
                   "name": uuid.uuid4().hex[:20],
                   "position": {"x": 12, "y": ny, "z": 4000 + ni, "width": 186, "height": 28, "tabOrder": 4000 + ni},
                   "visual": {"visualType": "actionButton", "objects": {
                       "icon": [{"properties": {"shapeType": lit("'blank'")}}],
                       "fill": [{"properties": {"show": lit("false")}}],
                       "outline": [{"properties": {"show": lit("false")}}],
                       "text": [{"properties": {"show": lit("false")}}]},
                       "visualContainerObjects": {
                           "visualLink": [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                                          "navigationSection": lit(f"'{page_ids[ni]}'")}}]},
                       "drillFilterOtherVisuals": True},
                   "howCreated": "InsertVisualButton"}
            vis.append(btn)
        for vi, v in enumerate(vis):
            v["name"] = f"p{pi + 1}v{vi + 1:02d}"
            vd = pd_ / "visuals" / v["name"]
            vd.mkdir()
            (vd / "visual.json").write_text(json.dumps(v, indent=2))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    (OUT / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    build_model(OUT)
    build_report(OUT, HERE / "Olist_Dark_Theme.json")
    n = sum(1 for _ in OUT.rglob("*") if _.is_file())
    print(f"PBIP written to {OUT} ({n} files)")


if __name__ == "__main__":
    main()

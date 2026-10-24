"""Generate a SMALL SYNTHETIC dataset with the exact Olist schema.

Purpose: test the pipeline end-to-end before/without downloading the real data.
NEVER report numbers from this data -- use the real Kaggle dataset for analysis.

  python scripts/generate_sample_data.py --customers 8000
"""
import argparse
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402

STATES = {"SP": (-23.55, -46.63, "sao paulo", .42), "RJ": (-22.90, -43.20, "rio de janeiro", .13),
          "MG": (-19.92, -43.94, "belo horizonte", .12), "RS": (-30.03, -51.23, "porto alegre", .055),
          "PR": (-25.43, -49.27, "curitiba", .05), "SC": (-27.59, -48.55, "florianopolis", .037),
          "BA": (-12.97, -38.50, "salvador", .034), "DF": (-15.79, -47.88, "brasilia", .021),
          "GO": (-16.68, -49.25, "goiania", .02), "ES": (-20.32, -40.34, "vitoria", .02),
          "PE": (-8.05, -34.88, "recife", .017), "CE": (-3.73, -38.52, "fortaleza", .013),
          "PA": (-1.46, -48.50, "belem", .01), "AM": (-3.12, -60.02, "manaus", .008)}
CATS = {"cama_mesa_banho": ("bed_bath_table", 90), "beleza_saude": ("health_beauty", 130),
        "esporte_lazer": ("sports_leisure", 115), "moveis_decoracao": ("furniture_decor", 110),
        "informatica_acessorios": ("computers_accessories", 120), "utilidades_domesticas": ("housewares", 90),
        "relogios_presentes": ("watches_gifts", 200), "telefonia": ("telephony", 70),
        "ferramentas_jardim": ("garden_tools", 110), "automotivo": ("auto", 140),
        "brinquedos": ("toys", 115), "perfumaria": ("perfumery", 120),
        "eletronicos": ("electronics", 60), "pet_shop": ("pet_shop", 105)}

uid = lambda: uuid.uuid4().hex  # noqa: E731
POS_TXT = ["Produto ótimo, chegou antes do prazo. Recomendo!", "Muito bom, gostei bastante", "Excelente qualidade",
           "Tudo certo, entrega rápida", "Adorei o produto, parabéns"]
MID_TXT = ["Produto ok, mas a embalagem veio amassada", "Razoável", "Chegou, mas demorou um pouco"]
NEG_TXT = ["Não gostei, veio quebrado", "Veio a cor errada", "Faltou um item no pedido",
           "Produto de péssima qualidade", "Não funciona, quero devolução", "Atendimento horrível, sem resposta"]
LATE_TXT = ["Ainda não recebi meu produto, atrasou muito", "Entrega atrasada, péssimo",
            "Prazo de entrega não cumprido"]


def main(n_customers: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    out = config.RAW_DIR
    st_codes = list(STATES)
    st_p = np.array([STATES[s][3] for s in st_codes]); st_p /= st_p.sum()

    # sellers
    n_sellers = max(50, n_customers // 30)
    s_state = rng.choice(st_codes, n_sellers, p=st_p)
    sellers = pd.DataFrame({"seller_id": [uid() for _ in range(n_sellers)],
                            "seller_zip_code_prefix": rng.integers(1000, 99999, n_sellers),
                            "seller_city": [STATES[s][2] for s in s_state], "seller_state": s_state})
    # products
    n_products = max(200, n_customers // 4)
    cat_keys = list(CATS)
    p_cat = rng.choice(cat_keys, n_products)
    products = pd.DataFrame({
        "product_id": [uid() for _ in range(n_products)], "product_category_name": p_cat,
        "product_name_lenght": rng.integers(20, 64, n_products),
        "product_description_lenght": rng.integers(100, 3000, n_products),
        "product_photos_qty": rng.integers(1, 6, n_products),
        "product_weight_g": rng.integers(100, 15000, n_products),
        "product_length_cm": rng.integers(10, 80, n_products),
        "product_height_cm": rng.integers(2, 60, n_products),
        "product_width_cm": rng.integers(8, 60, n_products)})
    base_price = np.array([CATS[c][1] for c in p_cat]) * rng.lognormal(0, 0.5, n_products)
    product_price = dict(zip(products.product_id, base_price.round(2)))
    product_seller = dict(zip(products.product_id, rng.choice(sellers.seller_id, n_products)))

    # customers (unique person) -> each order gets its own customer_id (Olist quirk)
    unique_ids = [uid() for _ in range(n_customers)]
    c_state = rng.choice(st_codes, n_customers, p=st_p)
    n_orders_per = rng.choice([1, 2, 3, 4], n_customers, p=[.94, .045, .01, .005])

    start, end = pd.Timestamp("2016-10-01"), pd.Timestamp("2018-08-31")
    span = (end - start).days
    # growth trend: more orders later in the period
    first_offsets = (np.sqrt(rng.random(n_customers)) * span).astype(int)

    cust_rows, order_rows, item_rows, pay_rows, rev_rows = [], [], [], [], []
    for i, u in enumerate(unique_ids):
        t = start + pd.Timedelta(days=int(first_offsets[i]))
        for k in range(n_orders_per[i]):
            if k > 0:
                t = t + pd.Timedelta(days=int(rng.integers(20, 300)))
                if t > end:
                    break
            t_full = t + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
            cid, oid = uid(), uid()
            st = c_state[i]
            cust_rows.append((cid, u, int(rng.integers(1000, 99999)), STATES[st][2], st))
            status = rng.choice(["delivered", "shipped", "canceled", "unavailable", "invoiced"],
                                p=[.97, .012, .007, .006, .005])
            est = t_full + pd.Timedelta(days=int(rng.integers(15, 35)))
            far = st not in ("SP", "RJ", "MG", "PR")
            deliv_days = rng.gamma(4, 3.5 if far else 2.2)
            delivered = t_full + pd.Timedelta(days=float(deliv_days)) if status == "delivered" else pd.NaT
            if status == "delivered" and rng.random() < .06:
                delivered = est + pd.Timedelta(days=int(rng.integers(1, 20)))
            order_rows.append((oid, cid, status, t_full, t_full + pd.Timedelta(hours=int(rng.integers(0, 48))),
                               t_full + pd.Timedelta(days=int(rng.integers(1, 5))) if status in ("delivered", "shipped") else pd.NaT,
                               delivered, est.normalize()))
            n_items = rng.choice([1, 2, 3], p=[.88, .09, .03])
            total = 0.0
            for j in range(1, n_items + 1):
                pid = rng.choice(products.product_id)
                price = product_price[pid]
                freight = round(float(rng.uniform(8, 45)) * (1.6 if far else 1), 2)
                total += price + freight
                item_rows.append((oid, j, pid, product_seller[pid], t_full + pd.Timedelta(days=3), price, freight))
            ptype = rng.choice(["credit_card", "boleto", "voucher", "debit_card"], p=[.74, .19, .055, .015])
            inst = int(rng.choice([1, 2, 3, 4, 6, 8, 10])) if ptype == "credit_card" else 1
            pay_rows.append((oid, 1, ptype, inst, round(total, 2)))
            if status == "delivered":
                late = delivered > est
                score = int(rng.choice([1, 2, 3, 4, 5], p=[.45, .15, .15, .1, .15] if late else [.06, .03, .08, .2, .63]))
                rd = delivered + pd.Timedelta(days=1)
                pool = NEG_TXT if score <= 2 else (POS_TXT if score >= 4 else MID_TXT)
                msg = pool[int(rng.integers(0, len(pool)))] if rng.random() < .45 else None
                if late and score <= 2 and msg is not None:
                    msg = LATE_TXT[int(rng.integers(0, len(LATE_TXT)))]
                rev_rows.append((uid(), oid, score, None, msg, rd.normalize(), rd + pd.Timedelta(days=1)))

    customers = pd.DataFrame(cust_rows, columns=["customer_id", "customer_unique_id", "customer_zip_code_prefix",
                                                 "customer_city", "customer_state"])
    orders = pd.DataFrame(order_rows, columns=["order_id", "customer_id", "order_status", "order_purchase_timestamp",
                                               "order_approved_at", "order_delivered_carrier_date",
                                               "order_delivered_customer_date", "order_estimated_delivery_date"])
    items = pd.DataFrame(item_rows, columns=["order_id", "order_item_id", "product_id", "seller_id",
                                             "shipping_limit_date", "price", "freight_value"])
    pays = pd.DataFrame(pay_rows, columns=["order_id", "payment_sequential", "payment_type",
                                           "payment_installments", "payment_value"])
    reviews = pd.DataFrame(rev_rows, columns=["review_id", "order_id", "review_score", "review_comment_title",
                                              "review_comment_message", "review_creation_date",
                                              "review_answer_timestamp"])
    geo_rows = []
    for st, (lat, lng, city, _) in STATES.items():
        for _ in range(30):
            geo_rows.append((int(rng.integers(1000, 99999)), lat + rng.normal(0, .3), lng + rng.normal(0, .3), city, st))
    geo = pd.DataFrame(geo_rows, columns=["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
                                          "geolocation_city", "geolocation_state"])
    trans = pd.DataFrame([(k, v[0]) for k, v in CATS.items()],
                         columns=["product_category_name", "product_category_name_english"])

    for key, df in {"customers": customers, "orders": orders, "order_items": items, "payments": pays,
                    "reviews": reviews, "products": products, "sellers": sellers, "geolocation": geo,
                    "category_translation": trans}.items():
        df.to_csv(out / config.RAW_FILES[key], index=False)
    print(f"SYNTHETIC sample written to {out}: {len(orders):,} orders, {customers.customer_unique_id.nunique():,} customers")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=8000)
    main(ap.parse_args().customers)

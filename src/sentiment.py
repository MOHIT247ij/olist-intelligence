"""Review sentiment & complaint themes for Olist (Portuguese review text).

Approach (fast, free, explainable -- runs on all ~40k comments in seconds):
  1. Portuguese sentiment lexicon score on the comment text (with simple negation handling)
  2. Combined with the star rating -> final label: positive / neutral / negative
  3. Complaint themes via keyword groups (delivery delay, wrong item, missing item, quality, ...)
  4. Optional: Gemini summarises a sample of negative comments into business insights (src/ai)
"""
import re
import unicodedata

import pandas as pd

POS = {"otimo", "otima", "excelente", "bom", "boa", "perfeito", "perfeita", "recomendo", "adorei", "amei", "gostei",
       "rapido", "rapida", "satisfeito", "satisfeita", "maravilhoso", "maravilhosa", "lindo", "linda", "parabens",
       "qualidade", "eficiente", "certinho", "correto", "antes", "super", "top", "show", "obrigado", "obrigada",
       "confiavel", "agradavel", "bem", "feliz", "nota", "dez", "pontual", "chegou", "recebi", "recebido",
       "funciona", "entregue", "certo", "certa", "tudo"}
NEG = {"ruim", "pessimo", "pessima", "horrivel", "defeito", "defeituoso", "quebrado", "quebrada", "errado", "errada",
       "atraso", "atrasado", "atrasou", "demora", "demorou", "nunca", "faltou", "falta", "faltando", "decepcao",
       "decepcionado", "decepcionada", "insatisfeito", "insatisfeita", "lixo", "fraude", "golpe", "enganosa",
       "pior", "problema", "reclamacao", "devolver", "devolucao", "reembolso", "cancelar", "cancelado", "absurdo",
       "descaso", "danificado", "danificada", "diferente", "trocado", "incompleto", "aguardando"}
# English + Hinglish words so uploaded (non-Brazilian) reviews are scored too
POS |= {"great", "excellent", "good", "nice", "awesome", "amazing", "love", "loved", "perfect", "fast", "quick",
        "recommend", "happy", "satisfied", "value", "best", "fantastic", "accha", "achha", "badhiya", "mast", "sahi"}
NEG |= {"bad", "poor", "worst", "terrible", "awful", "damaged", "broken", "late", "delay", "delayed", "wrong",
        "refund", "return", "defective", "fake", "cheap", "disappointed", "slow", "missing", "bekar", "ghatiya",
        "kharab", "bakwas"}
NEGATORS = {"nao", "nem", "nunca", "jamais", "sem", "not", "no", "never", "nahi", "nahin", "without"}

THEMES_EN = {
    "Delivery delay / not received": ["late", "delay", "not received", "not delivered", "still waiting"],
    "Wrong / different product": ["wrong", "different", "size"],
    "Missing items": ["missing", "incomplete"],
    "Damaged / poor quality": ["damaged", "broken", "poor quality", "defective", "quality"],
    "Customer service / no response": ["customer care", "support", "no response", "service"],
    "Refund / cancellation": ["refund", "return", "cancel"],
}
THEMES = {
    "Delivery delay / not received": ["atras", "demor", "prazo", "nao chegou", "nao recebi", "ainda nao", "aguardando",
                                      "nao foi entregue", "entrega"],
    "Wrong / different product": ["errado", "errada", "diferente", "trocad", "outro produto", "nao era"],
    "Missing items": ["faltou", "falta", "faltando", "incomplet", "apenas um", "so veio", "somente um", "veio so"],
    "Damaged / poor quality": ["quebrad", "defeito", "danific", "qualidade", "ruim", "nao funciona", "parou"],
    "Customer service / no response": ["atendimento", "resposta", "contato", "sac", "ninguem", "nao respond"],
    "Refund / cancellation": ["reembolso", "devolu", "estorno", "cancel", "dinheiro de volta"],
}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text).lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def lexicon_score(text: str) -> float:
    """Score in [-1, 1]. A negator flips the sentiment of the next word ('nao gostei' -> negative)."""
    words = normalize(text).split()
    if not words:
        return 0.0
    score, flip = 0, False
    for w in words:
        if w in NEGATORS:
            flip = True
            continue
        base = w if (w in POS or w in NEG) else w.rstrip("s")       # crude plural handling
        s = 1 if base in POS else (-1 if base in NEG else 0)
        score += -s if flip else s
        flip = False                                                # negation scope = next word only
    return max(-1.0, min(1.0, score / 3))


def themes_of(text: str) -> list[str]:
    t = normalize(text)
    return [name for name, keys in THEMES.items() if any(k in t for k in keys + THEMES_EN.get(name, []))]


def analyze(reviews: pd.DataFrame, orders: pd.DataFrame | None = None) -> pd.DataFrame:
    """reviews: raw olist_order_reviews_dataset. Returns one row per review with sentiment + themes."""
    r = reviews.sort_values("review_answer_timestamp").drop_duplicates("order_id", keep="last").copy()
    r["text"] = (r["review_comment_title"].fillna("") + " " + r["review_comment_message"].fillna("")).str.strip()
    r["has_text"] = r["text"].str.len() > 0
    r["text_score"] = r["text"].map(lexicon_score)
    star = (r["review_score"] - 3) / 2                                   # 1..5 -> -1..1
    r["sentiment_score"] = (0.6 * star + 0.4 * r["text_score"]).where(r["has_text"], star)
    r["sentiment"] = pd.cut(r["sentiment_score"], [-1.01, -0.2, 0.2, 1.01], labels=["negative", "neutral", "positive"])
    r["themes"] = r["text"].map(lambda t: "|".join(themes_of(t)) if t else "")
    r["review_month"] = pd.to_datetime(r["review_creation_date"]).dt.to_period("M").astype(str)
    if orders is not None:
        r = r.merge(orders[["order_id", "customer_state", "is_late"]], on="order_id", how="left")
    return r[["review_id", "order_id", "review_score", "has_text", "text", "text_score", "sentiment_score",
              "sentiment", "themes", "review_month"] + (["customer_state", "is_late"] if orders is not None else [])]


def sentiment_by_month(a: pd.DataFrame) -> pd.DataFrame:
    m = a.groupby(["review_month", "sentiment"], observed=True).size().unstack(fill_value=0)
    for c in ("positive", "neutral", "negative"):
        if c not in m:
            m[c] = 0
    m["total"] = m[["positive", "neutral", "negative"]].sum(axis=1)
    m = m[m["total"] >= 30]
    for c in ("positive", "neutral", "negative"):
        m[f"{c}_pct"] = m[c] / m["total"] * 100
    return m.reset_index()


def complaint_themes(a: pd.DataFrame) -> pd.DataFrame:
    neg = a[(a["sentiment"] == "negative") & a["has_text"]]
    ex = neg.assign(theme=neg["themes"].str.split("|")).explode("theme")
    ex = ex[ex["theme"].fillna("") != ""]
    t = ex.groupby("theme").agg(complaints=("review_id", "count"), avg_stars=("review_score", "mean"))
    t["share_of_negative_comments_pct"] = t["complaints"] / max(len(neg), 1) * 100
    return t.sort_values("complaints", ascending=False).reset_index()


def negative_samples(a: pd.DataFrame, n: int = 40) -> list[str]:
    neg = a[(a["sentiment"] == "negative") & (a["text"].str.len() > 25)]
    return neg.sample(min(n, len(neg)), random_state=42)["text"].str[:300].tolist() if len(neg) else []

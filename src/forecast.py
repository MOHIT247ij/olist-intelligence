"""Weekly sales forecasting: GBM (lag features) + naive baseline ensemble, with hold-out backtest.

- Aggregates revenue weekly; drops the last partial week (Olist data ends abruptly).
- Features: lags (1,2,3,4,52 if available), rolling means, week-of-year seasonality, trend.
- Model: GradientBoosting vs Seasonal-Naive baseline; recursive multi-step forecast.
- Metrics: MAPE, MAE on a hold-out of the last N weeks.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error

LAGS = [1, 2, 3, 4, 8]


def weekly_series(orders: pd.DataFrame, min_share: float = 0.1, tail_ratio: float = 0.7) -> pd.Series:
    """Weekly revenue, cleaned for forecasting:
    - keep the longest CONTIGUOUS run of 'active' weeks (drops sparse starts / gaps, e.g. Olist 2016)
    - drop trailing weeks that are clearly cut off by the data export (e.g. Olist late Aug 2018)."""
    v = orders[~orders["order_status"].isin(["canceled", "unavailable"])]
    v = v.assign(purchase_date=pd.to_datetime(v["purchase_date"]))
    rev = v.set_index("purchase_date")["product_revenue"].resample("W-MON", label="left", closed="left").sum()
    cnt = v.set_index("purchase_date")["order_id"].resample("W-MON", label="left", closed="left").count()
    active = cnt >= max(1, cnt[cnt > 0].median() * min_share)
    best, cur_start, best_len = (None, None), None, 0
    for i, ok in enumerate(list(active) + [False]):
        if ok and cur_start is None:
            cur_start = i
        elif not ok and cur_start is not None:
            if i - cur_start > best_len:
                best, best_len = (cur_start, i), i - cur_start
            cur_start = None
    if best[0] is not None:
        rev, cnt = rev.iloc[best[0]:best[1]], cnt.iloc[best[0]:best[1]]
    while len(cnt) > 10 and cnt.iloc[-1] < tail_ratio * cnt.iloc[-9:-1].median():
        rev, cnt = rev.iloc[:-1], cnt.iloc[:-1]
    return rev.rename("revenue")


def _features(hist: list[float], date: pd.Timestamp, t: int) -> list[float]:
    h = np.asarray(hist)
    row = [h[-l] if len(h) >= l else h[0] for l in LAGS]
    row += [h[-4:].mean(), h[-8:].mean(), h[-4:].std() if len(h) >= 4 else 0.0]
    woy = date.isocalendar().week
    row += [np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52), t,
            1.0 if (date.month == 11 and date.day >= 20) else 0.0]  # Black Friday flag
    return row


def _fit(series: pd.Series) -> GradientBoostingRegressor:
    X, y = [], []
    vals = series.tolist()
    for t in range(max(LAGS), len(vals)):
        X.append(_features(vals[:t], series.index[t], t))
        y.append(vals[t])
    m = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)
    return m.fit(np.array(X), np.array(y))


def _recursive(model, series: pd.Series, horizon: int) -> pd.Series:
    hist = series.tolist()
    idx = pd.date_range(series.index[-1] + pd.Timedelta(weeks=1), periods=horizon, freq="W-MON")
    preds = []
    for i, d in enumerate(idx):
        p = float(model.predict(np.array([_features(hist, d, len(series) + i)]))[0])
        preds.append(max(p, 0.0))
        hist.append(p)
    return pd.Series(preds, index=idx, name="forecast")


def backtest(series: pd.Series, test_weeks: int = 12) -> dict:
    """Hold out the last `test_weeks`; final forecast = 50/50 ensemble of GBM + 4-week-average baseline
    (more robust than either alone on real data)."""
    train, test = series.iloc[:-test_weeks], series.iloc[-test_weeks:]
    gbm = _recursive(_fit(train), train, test_weeks).values
    naive = np.repeat(train.iloc[-4:].mean(), test_weeks)
    ens = (gbm + naive) / 2
    return {
        "model_mape_pct": mean_absolute_percentage_error(test, ens) * 100,
        "model_mae": mean_absolute_error(test, ens),
        "gbm_mape_pct": mean_absolute_percentage_error(test, gbm) * 100,
        "baseline_mape_pct": mean_absolute_percentage_error(test, naive) * 100,
        "comparison": pd.DataFrame({"actual": test.values, "forecast": ens, "gbm": gbm, "baseline": naive},
                                   index=test.index),
    }


def forecast(series: pd.Series, horizon: int = 12, test_weeks: int = 12) -> dict:
    bt = backtest(series, test_weeks)
    gbm = _recursive(_fit(series), series, horizon)
    fc = (gbm + series.iloc[-4:].mean()) / 2
    err = (bt["comparison"]["actual"] - bt["comparison"]["forecast"]).std()   # band from backtest error
    out = pd.DataFrame({"forecast": fc, "lower": (fc - 1.28 * err).clip(lower=0), "upper": fc + 1.28 * err})
    return {"history": series, "forecast": out, "backtest": bt}

"""Cost forecasting and anomaly detection (pure, dependency-free).

Forecast: additive Holt-Winters with a damped trend and weekly seasonality
(period 7 on daily costs). Smoothing parameters are chosen by grid search on
one-step-ahead squared error. With fewer than two full seasons of history it
falls back to the median of recent days with a MAD-based interval (no trend
or season can be estimated yet).
Prediction intervals use the one-step residual standard deviation, widened
with the horizon.

Anomalies: a day is anomalous when its one-step-ahead forecast error is
extreme under a robust z-score (median / MAD of past errors). Using errors
instead of raw values means normal weekly patterns (cheaper weekends) are
not flagged; only departures from what the model expected are.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

Z = {0.80: 1.2816, 0.95: 1.96}
ALPHAS = (0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
BETAS = (0.0, 0.05, 0.1, 0.2)
GAMMAS = (0.05, 0.1, 0.2, 0.4)
PHI = 0.9  # trend damping


@dataclass
class Fit:
    method: str
    alpha: float
    beta: float
    gamma: float
    level: float
    trend: float
    season: list[float]
    one_step: list[float | None]   # in-sample one-step-ahead predictions (None during warm-up)
    sigma: float                    # residual std

    def predict(self, h: int) -> float:
        if self.method == "mean":
            return self.level
        damp = sum(PHI**i for i in range(1, h + 1))
        return self.level + damp * self.trend + self.season[(h - 1) % len(self.season)]


@dataclass
class Forecast:
    method: str
    points: list[dict]             # [{"h": 1, "value": .., "lo80": .., "hi80": .., "lo95": .., "hi95": ..}]
    params: dict = field(default_factory=dict)
    sigma: float = 0.0


def _holt_winters(x: Sequence[float], m: int, a: float, b: float, g: float) -> tuple[float, Fit]:
    level = sum(x[:m]) / m
    trend = (sum(x[m:2 * m]) / m - level) / m
    season = [x[i] - level for i in range(m)]
    sse, preds = 0.0, [None] * m
    for t in range(m, len(x)):
        s = season[t % m]
        pred = level + PHI * trend + s
        preds.append(pred)
        err = x[t] - pred
        sse += err * err
        new_level = a * (x[t] - s) + (1 - a) * (level + PHI * trend)
        trend = b * (new_level - level) + (1 - b) * PHI * trend
        season[t % m] = g * (x[t] - new_level) + (1 - g) * s
        level = new_level
    n = len(x) - m
    sigma = math.sqrt(sse / max(1, n - 3))
    # Rotate so season[0] is the slot of the next point.
    rot = [season[(len(x) + i) % m] for i in range(m)]
    return sse, Fit("holt_winters", a, b, g, level, trend, rot, preds, sigma)


def fit(series: Sequence[float], period: int = 7) -> Fit:
    x = [float(v) for v in series]
    if len(x) >= 2 * period:
        best = min((_holt_winters(x, period, a, b, g) for a in ALPHAS for b in BETAS for g in GAMMAS),
                   key=lambda r: r[0])
        return best[1]
    # Short history: robust level (median) and spread (MAD), so a single
    # incident day cannot drag the forecast or blow up the interval.
    recent = x[-period:] or [0.0]
    level = _median(recent)
    sigma = 1.4826 * _median([abs(v - level) for v in recent]) if len(recent) > 1 else 0.0
    sigma = max(sigma, 0.02 * abs(level))
    return Fit("mean", 0, 0, 0, level, 0.0, [0.0], [None] * len(x), sigma)


def forecast(series: Sequence[float], horizon: int, period: int = 7) -> Forecast:
    f = fit(series, period)
    points = []
    for h in range(1, horizon + 1):
        v = max(0.0, f.predict(h))
        if f.method == "holt_winters":
            sd = f.sigma * math.sqrt(1 + (h - 1) * f.alpha**2)
        else:   # stationary level: the band does not grow with the horizon
            sd = f.sigma * math.sqrt(1 + 1 / 7)
        points.append({"h": h, "value": round(v, 4),
                       "lo80": round(max(0.0, v - Z[0.80] * sd), 4), "hi80": round(v + Z[0.80] * sd, 4),
                       "lo95": round(max(0.0, v - Z[0.95] * sd), 4), "hi95": round(v + Z[0.95] * sd, 4)})
    return Forecast(f.method, points, {"alpha": f.alpha, "beta": f.beta, "gamma": f.gamma, "phi": PHI},
                    round(f.sigma, 4))


def backtest_mape(series: Sequence[float], horizon: int = 7, period: int = 7) -> float | None:
    """Hold out the last ``horizon`` points, forecast them, return MAPE (0..1)."""
    if len(series) < horizon + 2 * period:
        return None
    train, test = list(series[:-horizon]), list(series[-horizon:])
    pred = [p["value"] for p in forecast(train, horizon, period).points]
    errs = [abs(p - a) / a for p, a in zip(pred, test, strict=True) if a > 0]
    return round(sum(errs) / len(errs), 4) if errs else None


def month_end_projection(month_to_date: Sequence[float], history: Sequence[float], days_remaining: int,
                         period: int = 7) -> dict:
    """Actual so far + forecast for the rest of the month, with an 80 % interval.

    ``history`` is the full daily series up to yesterday (includes the
    month-to-date days); the model is fitted on it.
    """
    actual = sum(month_to_date)
    if days_remaining <= 0:
        return {"actual": round(actual, 2), "forecast_remaining": 0.0, "projected": round(actual, 2),
                "lo80": round(actual, 2), "hi80": round(actual, 2)}
    fc = forecast(history, days_remaining, period)
    rest = sum(p["value"] for p in fc.points)
    # Errors over consecutive days are positively correlated; summing the
    # per-day interval half-widths is a conservative (wider) bound.
    half = sum(p["hi80"] - p["value"] for p in fc.points)
    return {"actual": round(actual, 2), "forecast_remaining": round(rest, 2), "projected": round(actual + rest, 2),
            "lo80": round(max(actual, actual + rest - half), 2), "hi80": round(actual + rest + half, 2),
            "method": fc.method}


@dataclass
class Anomaly:
    index: int
    value: float
    expected: float
    score: float
    delta: float


def detect_anomalies(series: Sequence[float], period: int = 7, threshold: float = 3.5, min_abs_delta: float = 1.0,
                     min_rel_delta: float = 0.10) -> list[Anomaly]:
    """Robust z-score of one-step-ahead errors (Holt-Winters) or of deviations
    from the trailing median (short history)."""
    x = [float(v) for v in series]
    if len(x) < 7:   # 3 baseline days + 3 past errors + the point being judged
        return []
    if len(x) >= 2 * period + 2:
        f = fit(x, period)
        expected = f.one_step
    else:
        # Young series: trailing median of up to one period, from day 3 on, so a
        # spike can be judged after a week instead of after ~1.5 periods.
        expected = [None] * 3 + [_median(x[max(0, i - period):i]) for i in range(3, len(x))]
    errors = [(i, x[i] - e) for i, e in enumerate(expected) if e is not None]
    out = []
    for k, (i, err) in enumerate(errors):
        past = [e for _, e in errors[:k]][-4 * period:]
        if len(past) < 3:
            continue
        med = _median(past)
        mad = _median([abs(e - med) for e in past])
        scale = max(1.4826 * mad, 0.02 * abs(expected[i] or 1.0), 1e-9)
        score = (err - med) / scale
        delta = x[i] - expected[i]
        if abs(score) > threshold and abs(delta) >= min_abs_delta and abs(delta) >= min_rel_delta * abs(expected[i]):
            out.append(Anomaly(i, x[i], round(expected[i], 4), round(score, 2), round(delta, 4)))
    return out


def _median(v: Sequence[float]) -> float:
    s = sorted(v)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

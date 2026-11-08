import math
import random

import pytest

from app.engines.forecast import backtest_mape, detect_anomalies, fit, forecast, month_end_projection


def weekly(days, base=40.0, weekend=-5.0, trend=0.0, noise=0.0, seed=3):
    r = random.Random(seed)
    return [base + trend * d + (weekend if d % 7 in (5, 6) else 0.0) + r.gauss(0, noise) for d in range(days)]


def test_holt_winters_learns_the_weekly_pattern():
    hist = weekly(28, noise=0.3)
    fc = forecast(hist, 7)
    assert fc.method == "holt_winters"
    values = [p["value"] for p in fc.points]
    # Days 28..34: 28 % 7 = 0 -> days 5,6 of the next week are the weekend.
    assert values[5] < values[0] - 3 and values[6] < values[1] - 3
    assert all(abs(v - e) < 1.5 for v, e in zip(values, weekly(35)[28:], strict=True))


def test_intervals_contain_the_point_and_widen():
    fc = forecast(weekly(28, noise=1.0), 14)
    for p in fc.points:
        assert p["lo95"] <= p["lo80"] <= p["value"] <= p["hi80"] <= p["hi95"]
    width = [p["hi80"] - p["lo80"] for p in fc.points]
    assert width[-1] >= width[0]


def test_short_history_falls_back_to_mean():
    fc = forecast([10, 12, 11, 13], 3)
    assert fc.method == "mean"
    assert fc.points[0]["value"] == pytest.approx(11.5)


def test_short_history_fallback_is_robust_to_a_spike():
    """Regression (seen in the UI): one incident day inflated the mean and made
    the 80 % band grow like a random walk to $0-$100 over 30 days."""
    hist = [40.8, 40.8, 36.2, 36.2, 40.8, 59.9, 40.8, 40.8, 40.8, 36.2]
    fc = forecast(hist, 30)
    first, last = fc.points[0], fc.points[-1]
    assert first["value"] == pytest.approx(40.8)
    assert last["hi80"] - last["lo80"] == pytest.approx(first["hi80"] - first["lo80"])
    assert last["hi80"] < 50


def test_trend_is_damped_not_extrapolated_forever():
    rising = weekly(28, weekend=0, trend=1.0)
    far = forecast(rising, 60).points[-1]["value"]
    linear = rising[-1] + 60
    assert rising[-1] < far < linear


def test_backtest_mape_is_small_on_regular_series():
    mape = backtest_mape(weekly(35, noise=0.5), horizon=7)
    assert mape is not None and mape < 0.05
    assert backtest_mape([1, 2, 3], horizon=7) is None


def test_month_end_projection_adds_actuals_and_forecast():
    hist = weekly(28, weekend=0, noise=0)          # flat 40 $/day
    proj = month_end_projection(hist[-10:], hist, days_remaining=20)
    assert proj["actual"] == pytest.approx(400)
    assert proj["projected"] == pytest.approx(400 + 20 * 40, rel=0.02)
    assert proj["lo80"] <= proj["projected"] <= proj["hi80"]
    done = month_end_projection([5, 5], [5] * 20, days_remaining=0)
    assert done["projected"] == done["actual"] == 10


def test_spike_is_an_anomaly_but_weekends_are_not():
    series = weekly(28, noise=0.3)
    series[20] += 25                               # a runaway job doubled one day's cost
    found = detect_anomalies(series)
    assert [a.index for a in found] == [20]
    assert found[0].delta > 20 and found[0].score > 3.5


def test_steady_series_has_no_anomalies():
    assert detect_anomalies(weekly(28, noise=0.3)) == []


def test_small_absolute_blips_are_ignored():
    series = [1.0] * 20
    series[15] = 1.5                               # +50 % but only $0.50
    assert detect_anomalies(series, min_abs_delta=1.0) == []


def test_short_history_uses_median_baseline():
    series = [10.0, 10.2, 9.9, 10.1, 10.0, 9.8, 10.1, 10.0, 10.2, 9.9, 10.1, 30.0]
    assert [a.index for a in detect_anomalies(series)] == [11]
    assert detect_anomalies(series[:6]) == []         # too short to judge


def test_young_cluster_spike_is_caught_within_two_weeks():
    """Regression (found live): with 13 days of history and a spike 5 days ago,
    the short-history path never judged the spike."""
    week = [40.8, 40.8, 40.8, 40.8, 40.8, 36.2, 36.2]
    series = week + [40.8, 59.9, 40.8, 40.8, 40.8, 36.2]
    assert [a.index for a in detect_anomalies(series, min_abs_delta=5)] == [8]


def test_fit_on_constant_series_is_stable():
    f = fit([20.0] * 21)
    assert math.isfinite(f.sigma) and f.predict(1) == pytest.approx(20.0, abs=1e-6)

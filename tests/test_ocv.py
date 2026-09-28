"""The open-circuit voltage curve."""

from __future__ import annotations

import numpy as np
import pytest

from celllab import ocv
from celllab.measurements import Measurement


def true_ocv(q: np.ndarray) -> np.ndarray:
    return 4.2 - 0.35 * q - 0.05 * np.sin(2.0 * q) - 0.3 * np.exp(6 * (q - 2.8))


def _hppc(step_ah: float = 0.3, levels: int = 9) -> Measurement:
    """Rests of an hour at the true open-circuit voltage, separated by 0.9 A steps."""
    t, i = [0.0], [0.0]
    for _ in range(levels):
        steps = round(step_ah / 0.9 * 3600)
        t += [t[-1] + 1.0 * (k + 1) for k in range(steps)]
        i += [-0.9] * steps
        t += [t[-1] + 10.0 * (k + 1) for k in range(361)]
        i += [0.0] * 361
    time, current = np.array(t), np.array(i)
    q = -np.concatenate(([0.0], np.cumsum(np.diff(time) * (current[1:] + current[:-1]) / 2))) / 3600
    voltage = true_ocv(q) + 0.05 * current  # under current, a 50 mOhm drop
    return Measurement("hppc", time, voltage, current, np.full_like(time, 25.0))


def _c20(polarisation_v: float = 0.012, noise: float = 0.0) -> Measurement:
    t = np.arange(0.0, 20 * 3600.0, 60.0)
    current = np.where(t < 19 * 3600, -0.15, 0.0)
    q = 0.15 * np.minimum(t, 19 * 3600) / 3600
    rng = np.random.default_rng(3)
    voltage = true_ocv(q) - polarisation_v + noise * rng.standard_normal(len(t))
    return Measurement("c20", t, voltage, current, np.full_like(t, 25.0))


def test_rest_points_are_the_ends_of_the_hour_long_rests() -> None:
    points = ocv.rest_points(_hppc())
    assert len(points) == 10
    assert points[0].charge_ah == 0.0
    # Each step is 1200 samples 1 s apart at 0.9 A: 1199 full intervals, plus the 1 s interval
    # from the rest before it and the 10 s interval to the rest after it, over which the
    # trapezoid rule sees the mean of 0.9 A and 0.
    per_step_ah = (1199 * 0.9 + 0.45 * 1.0 + 0.45 * 10.0) / 3600
    for k, p in enumerate(points[1:], start=1):
        assert p.charge_ah == pytest.approx(k * per_step_ah, abs=1e-9)
        assert p.voltage_v == pytest.approx(true_ocv(np.array(p.charge_ah)), abs=1e-9)


def test_curve_passes_through_rest_points_and_follows_the_c20_shape() -> None:
    curve, points = ocv.build(_hppc(), _c20())
    for p in points:
        assert curve(p.charge_ah) == pytest.approx(p.voltage_v, abs=2e-4)
    q = np.linspace(0.1, 2.6, 200)
    assert curve(q) == pytest.approx(true_ocv(q), abs=1e-3)


def test_c20_noise_is_made_non_increasing() -> None:
    q, v = ocv.c20_discharge(_c20(noise=2e-4))
    assert np.all(np.diff(v) <= 0)
    assert q[0] == 0.0


def test_leave_one_out_is_small_for_a_smooth_cell() -> None:
    errors = ocv.leave_one_out(_hppc(), _c20())
    assert len(errors) == 8
    assert np.max(np.abs(errors)) < 2e-3


def test_c20_without_discharge_is_refused() -> None:
    m = _c20()
    flat = Measurement("x", m.time_s, m.voltage_v, np.zeros_like(m.time_s), m.temperature_c)
    with pytest.raises(ValueError, match="no discharge"):
        ocv.c20_discharge(flat)
    broken = m.current_a.copy()
    broken[100] = 0.0
    with pytest.raises(ValueError, match="interrupted"):
        ocv.c20_discharge(Measurement("x", m.time_s, m.voltage_v, broken, m.temperature_c))


def test_a_curve_that_would_rise_is_refused() -> None:
    hppc = _hppc()
    bumped = hppc.voltage_v.copy()
    k = ocv.rest_points(hppc)[4].index
    bumped[k] += 0.2  # one rest point far above its neighbours
    m = Measurement("hppc", hppc.time_s, bumped, hppc.current_a, hppc.temperature_c)
    with pytest.raises(ValueError, match="must not rise"):
        ocv.build(m, _c20())


def test_rest_points_beyond_the_c20_discharge_are_refused() -> None:
    short = _c20()
    cut = short.window(0, 200)  # 3.3 h of C/20: 0.5 Ah, less than the HPPC reaches
    with pytest.raises(ValueError, match="beyond the end"):
        ocv.build(_hppc(), cut)

"""The identification recovers the parameters of a cell whose parameters are known."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from conftest import linear_ocv, pulse_train

from celllab import identify
from celllab.identify import NO_CHARGE_TRANSFER_A, fit_window
from celllab.measurements import Measurement
from celllab.ocv import RestPoint, rest_points


@pytest.mark.parametrize("temperature_c", [-20.0, 25.0])
def test_fit_recovers_known_parameters(true_values: dict[str, float], temperature_c: float) -> None:
    ocv = linear_ocv()
    values = dict(true_values, i0_a=0.2 if temperature_c < 0 else 5.0)
    data = pulse_train(ocv, values, temperature_c, offset_ah=0.5)
    fit = fit_window(data, ocv, charge_offset_ah=0.5)
    for name, expected in values.items():
        assert fit.values[name] == pytest.approx(expected, rel=0.02), name
    assert fit.rms_v < 1e-4
    assert fit.charge_ah == pytest.approx(0.5)
    assert fit.temperature_c == pytest.approx(temperature_c)


def test_fit_is_not_misled_by_an_error_in_the_ocv_slope(true_values: dict[str, float]) -> None:
    # The curve the fit is given passes through the rest voltage at the start of the window, as
    # ocv.py makes it do, but the cell's real curve falls 0.1 V/Ah faster there.
    given = linear_ocv(top_v=4.2, slope_v_per_ah=0.4)
    real = linear_ocv(top_v=4.2 + 0.1 * 0.5, slope_v_per_ah=0.5)
    data = pulse_train(real, true_values, offset_ah=0.5)
    fit = fit_window(data, given, charge_offset_ah=0.5)
    for name, expected in true_values.items():
        assert fit.values[name] == pytest.approx(expected, rel=0.02), name
    # Without the correction the slow RC pair takes up the slope error: R2 and tau2 triple
    # (docs/method.md, section 3).
    plain = fit_window(data, given, charge_offset_ah=0.5, slope_correction=False)
    for name in ("r2_ohm", "tau2_s"):
        assert 2.9 < plain.values[name] / true_values[name] < 3.3, name


def test_levels_record_their_longest_rest_and_identifiability(
    true_values: dict[str, float],
) -> None:
    # A rest is measured from its first to its last sample without current: the hour-long rest
    # is sampled every 10 s, so it spans 3590 s; the 10-minute rests, sampled every 2 s, 598 s.
    data = pulse_train(linear_ocv(), true_values)
    fit = fit_window(data, linear_ocv(), 0.5)
    assert fit.longest_rest_s == pytest.approx(3590.0)
    assert fit.identifiable
    no_long_rest = data.window(0, int(np.searchsorted(data.time_s, 2700.0)))
    assert identify.longest_rest_s(no_long_rest) == pytest.approx(598.0)
    assert identify.longest_rest_s(no_long_rest.window(120, 160)) == 0.0


def test_linear_variant_has_no_charge_transfer(true_values: dict[str, float]) -> None:
    ocv = linear_ocv()
    values = dict(true_values, i0_a=1e6)  # the data have practically no charge-transfer term
    data = pulse_train(ocv, values)
    fit = fit_window(data, ocv, charge_offset_ah=0.5, charge_transfer=False)
    assert fit.values["i0_a"] == NO_CHARGE_TRANSFER_A
    for name in ("r0_ohm", "r1_ohm", "tau1_s", "r2_ohm", "tau2_s"):
        assert fit.values[name] == pytest.approx(values[name], rel=0.02), name


def test_linear_variant_fits_worse_when_charge_transfer_matters(
    true_values: dict[str, float],
) -> None:
    ocv = linear_ocv()
    values = dict(true_values, i0_a=0.1)
    data = pulse_train(ocv, values, temperature_c=-20.0)
    full = fit_window(data, ocv, 0.5)
    plain = fit_window(data, ocv, 0.5, charge_transfer=False)
    assert plain.rms_v > 20 * full.rms_v


def _test_with_levels(levels: int, recharge: bool, last_to_cutoff: bool) -> Measurement:
    """A sequence of pulse sets separated by hour-long rests, as the HPPC test runs."""
    ocv = linear_ocv()
    parts = [
        pulse_train(
            ocv,
            {
                "r0_ohm": 0.02,
                "r1_ohm": 0.005,
                "tau1_s": 3.0,
                "r2_ohm": 0.02,
                "tau2_s": 100.0,
                "i0_a": 5.0,
            },
        )
        for _ in range(levels)
    ]
    t = [parts[0].time_s]
    for part in parts[1:]:
        t.append(part.time_s[1:] + t[-1][-1])
    time = np.concatenate(t)
    current = np.concatenate([parts[0].current_a] + [p.current_a[1:] for p in parts[1:]])
    voltage = np.concatenate([parts[0].voltage_v] + [p.voltage_v[1:] for p in parts[1:]])
    if last_to_cutoff:
        voltage[-400:-360] = 2.8  # the final step reaches the cut-off
    if recharge:
        time = np.concatenate((time, time[-1] + np.arange(1, 1001) * 1.0))
        current = np.concatenate((current, np.full(1000, 1.5)))
        voltage = np.concatenate((voltage, np.full(1000, 3.9)))
    return Measurement("levels", time, voltage, current, np.full_like(time, 25.0))


def _rests(m: Measurement) -> list[RestPoint]:
    return rest_points(m)


@pytest.mark.parametrize("recharge", [True, False])
def test_windows_cover_each_pulse_set(recharge: bool) -> None:
    m = _test_with_levels(3, recharge, last_to_cutoff=False)
    points = _rests(m)
    ranges = identify.windows(m, points)
    assert len(ranges) == 3
    assert ranges[0][0] == 0
    for (a, b), (c, _) in itertools.pairwise(ranges):
        assert b == c + 1  # consecutive windows share the rest sample between them
        assert a < b
    for a, b in ranges:
        assert np.any(m.current_a[a:b] > 0.3)  # every window holds charge pulses


def test_fit_temperature_fits_every_window() -> None:
    # The sequence only exercises the bookkeeping: its parts are generated independently, so
    # their voltages do not share one open-circuit curve (parameter recovery is tested above).
    m = _test_with_levels(2, recharge=True, last_to_cutoff=False)
    points = _rests(m)
    fits = identify.fit_temperature(m, linear_ocv(), points)
    q = m.charge_removed_ah
    assert [f.charge_ah for f in fits] == pytest.approx(
        [q[a] for a, _ in identify.windows(m, points)]
    )
    for fit in fits:
        assert all(v > 0 for v in fit.values.values())
        assert fit.samples > 1000


def test_window_ends_before_a_step_to_the_cut_off() -> None:
    m = _test_with_levels(2, recharge=True, last_to_cutoff=True)
    ranges = identify.windows(m, _rests(m))
    a, b = ranges[-1]
    assert m.voltage_v[a:b].min() > 2.81

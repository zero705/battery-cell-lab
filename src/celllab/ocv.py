"""Open-circuit voltage: the voltage of the cell at rest, as a function of the charge removed.

Two tests of the dataset measure it, and neither alone is enough:

- the HPPC test rests the cell for an hour after each of its 9 to 11 steps down in state of
  charge. The voltage at the end of each rest, and at the start of the test, is the
  open-circuit voltage after discharge, but only at those 10 to 12 points;
- the C/20 test discharges the cell at 0.15 A, which traces the whole curve, but under current:
  the voltage lies below the open-circuit voltage by the cell's polarisation at 0.15 A.

The curve used here takes the shape of the C/20 discharge and moves it onto the rest points:
open-circuit voltage = C/20 discharge voltage + an offset that passes through every rest point,
interpolated between them (monotone cubic, PCHIP). Predicting each rest point from the others
(leave_one_out below; data/model.json records the result), this is off by 8.9 mV RMS over the
six temperatures, against 17.8 mV for a curve through the rest points alone
(tests/test_raw_data.py checks both figures).

The charge removed is counted from the full cell. The C/20 charge half is not used: at 0.15 A
the cycler's current accuracy (0.1 % of its 75 A range, ±75 mA) is half the current, and its
charge count disagrees with the discharge by up to 0.19 Ah, while the HPPC steps, at 0.87 to
0.9 A, count consistently with the discharge (at 25 degC both remove 2.78 Ah to 2.8 V).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import isotonic_regression

from celllab.measurements import Array, Measurement

REST_S = 3000.0  # the HPPC rests last 3600 s; a shorter rest is not an equilibrium point
REST_CURRENT_A = 0.01
C20_DISCHARGE_A = -0.05  # below this current the C/20 test is discharging


@dataclass(frozen=True)
class RestPoint:
    """The end of one long rest: charge removed (Ah), voltage (V), cell temperature, index."""

    charge_ah: float
    voltage_v: float
    temperature_c: float
    index: int


def rest_points(hppc: Measurement) -> list[RestPoint]:
    """The first sample, and the end of every rest longer than REST_S before the recharge."""
    q = hppc.charge_removed_ah
    resting = np.abs(hppc.current_a) < REST_CURRENT_A
    points = [RestPoint(0.0, float(hppc.voltage_v[0]), float(hppc.temperature_c[0]), 0)]
    change = np.flatnonzero(np.diff(resting.astype(np.int8))) + 1
    bounds = np.concatenate(([0], change, [len(hppc)]))
    for start, stop in itertools.pairwise(bounds):
        long_rest = hppc.time_s[stop - 1] - hppc.time_s[start] > REST_S
        if resting[start] and long_rest and q[stop - 1] > points[-1].charge_ah + 0.05:
            k = stop - 1
            points.append(
                RestPoint(float(q[k]), float(hppc.voltage_v[k]), float(hppc.temperature_c[k]), k)
            )
    return points


def c20_discharge(c20: Measurement) -> tuple[Array, Array]:
    """The discharge half of the C/20 test: charge removed from its start (Ah) and voltage.

    At -20 degC the logged voltage rises by up to 0.34 mV in 51 places, which is measurement
    noise: the voltage under a steady discharge cannot rise. It is replaced by the closest
    non-increasing sequence in the least-squares sense (isotonic regression), which moves no
    sample by more than 0.28 mV and leaves the other five temperatures unchanged.
    """
    k = np.flatnonzero(c20.current_a < C20_DISCHARGE_A)
    if len(k) == 0:
        raise ValueError(f"{c20.name}: no discharge")
    if np.any(np.diff(k) != 1):
        raise ValueError(f"{c20.name}: the discharge is interrupted")
    q = c20.charge_removed_ah
    voltage = isotonic_regression(c20.voltage_v[k], increasing=False).x
    return q[k] - q[k[0]], np.asarray(voltage, dtype=float)


@dataclass(frozen=True)
class OcvCurve:
    """Open-circuit voltage against charge removed, sampled on a fine grid."""

    charge_ah: Array
    voltage_v: Array

    def __call__(self, charge_ah: Array | float) -> Array:
        return np.asarray(np.interp(charge_ah, self.charge_ah, self.voltage_v), dtype=float)


GRID_AH = 0.005


def build(hppc: Measurement, c20: Measurement) -> tuple[OcvCurve, list[RestPoint]]:
    """The open-circuit voltage curve of one temperature, and the rest points it passes through."""
    points = rest_points(hppc)
    q_c20, v_c20 = c20_discharge(c20)
    q = np.array([p.charge_ah for p in points])
    v = np.array([p.voltage_v for p in points])
    if q[-1] > q_c20[-1]:
        raise ValueError("a rest point lies beyond the end of the C/20 discharge")
    offset = PchipInterpolator(q, v - np.interp(q, q_c20, v_c20), extrapolate=True)
    grid = np.arange(0.0, q_c20[-1], GRID_AH)
    curve = np.interp(grid, q_c20, v_c20) + offset(grid)
    if np.any(np.diff(curve) > 0):
        raise ValueError("the open-circuit voltage must not rise as charge is removed")
    return OcvCurve(grid, curve), points


def leave_one_out(hppc: Measurement, c20: Measurement) -> Array:
    """Error (V) of predicting each interior rest point from all the others."""
    points = rest_points(hppc)
    q_c20, v_c20 = c20_discharge(c20)
    q = np.array([p.charge_ah for p in points])
    v = np.array([p.voltage_v for p in points])
    errors = []
    for k in range(1, len(points) - 1):
        keep = np.r_[0:k, k + 1 : len(points)]
        offset = PchipInterpolator(q[keep], v[keep] - np.interp(q[keep], q_c20, v_c20))
        predicted = np.interp(q[k], q_c20, v_c20) + offset(q[k])
        errors.append(float(predicted - v[k]))
    return np.array(errors)

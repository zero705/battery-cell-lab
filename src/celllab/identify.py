"""Fitting the circuit parameters to the HPPC test.

At every state of charge the HPPC test runs four pulse pairs. Each one is a 10 s discharge pulse
(for example 1, 2, 4 and 6C), 40 s of rest, a 10 s charge pulse and 10 minutes of rest. Then
comes a 0.3C discharge step to the next state of charge and an hour of rest. One fit window goes
from the end of one hour-long rest to the end of the next, so it has all eight pulses, the step
and the relaxation after it (windows() handles the two ends of the test).

In each window the parameters are fitted to the measured voltage by least squares. Once tau1,
tau2 and i0 are fixed, the voltage is linear in R0, R1 and R2. So the search only runs over those
three, and at each step the resistances are solved exactly with R >= 0 (variable projection with
non-negative least squares). The search starts from several points and keeps the best one, so it
doesn't get stuck in a local minimum. tau1 is searched in 0.1-20 s and tau2 in 20-2000 s, which
keeps the two RC pairs on separate time scales.

The window starts from rest (the RC voltages are zero). The open-circuit voltage along it is the
curve from ocv.py plus a straight-line correction in the charge removed, fitted together with
the resistances. Without it, an error in the slope of the curve inside the window (largest near
empty, where the curve is steep) gets taken up by the slow RC pair, and its resistance and time
constant come out much bigger than the cell's (a slope error of 0.1 V/Ah triples both in
tests/test_identify.py). The correction is only for the fit. The model uses the curve from
ocv.py.

A time constant can only be found from a relaxation at least as long as itself. A level whose
tau2 is longer than the longest rest in its window is marked as not identifiable, and the model
doesn't use it (model_file.py). This drops the lowest state of charge at 10, 25 and 40 degC,
where the window ends with a 10-minute rest and the fit puts tau2 at 634 to 934 s.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.optimize import least_squares, nnls

from celllab.ecm import PARAMETERS, charge_transfer_v, rc_response
from celllab.measurements import Array, Measurement
from celllab.ocv import REST_CURRENT_A, OcvCurve, RestPoint

TAU1_S = (0.1, 20.0)
TAU2_S = (20.0, 2000.0)
I0_A = (0.005, 100.0)
STARTS = list(itertools.product((1.0, 5.0), (60.0, 400.0), (0.1, 1.0, 10.0)))
RECHARGE_S = 600.0  # a charge longer than this is the recharge that ends the test
STEP_S = 60.0  # a discharge longer than this is a step to the next state of charge, not a pulse
PULSE_A = 0.3
CUTOFF_V = 2.8  # the lowest voltage the tests of the dataset discharge the cell to
# i0 of the model without the charge-transfer term: at 20 A, more than any current in the data
# (18.1 A), and 50 degC, eta = (2RT/F) asinh(20 / 2e9) is below 1e-9 V.
NO_CHARGE_TRANSFER_A = 1e9


@dataclass(frozen=True)
class LevelFit:
    """The parameters identified at one state of charge of one temperature."""

    charge_ah: float  # charge removed at the pulses
    temperature_c: float  # mean cell temperature during the pulses
    values: dict[str, float]
    rms_v: float  # RMS voltage error over the window
    pulse_rms_v: float  # RMS voltage error while a pulse or step flows
    samples: int
    longest_rest_s: float

    @property
    def identifiable(self) -> bool:
        """Whether the window rests long enough to show the slow time constant."""
        return self.values["tau2_s"] < self.longest_rest_s


def _runs(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    """[start, stop) of every run of True in mask."""
    change = np.flatnonzero(np.diff(mask.astype(np.int8))) + 1
    bounds = np.concatenate(([0], change, [len(mask)]))
    return [(int(a), int(b)) for a, b in itertools.pairwise(bounds) if mask[a]]


def windows(hppc: Measurement, points: list[RestPoint]) -> list[tuple[int, int]]:
    """Index ranges [start, stop) of the fit windows, one per state of charge with pulses.

    A window runs from the end of one long rest to the end of the next; the last one to the
    recharge that ends the test, or to the end of the file (25 degC stops before the recharge).
    A window without a charge pulse holds no pulse set and is dropped. Where the step of a
    window discharges the cell to the 2.8 V cut-off, where the cell is far from linear, the
    window ends before that step.
    """
    stop = len(hppc)
    for a, b in _runs(hppc.current_a > 0.05):
        if a > points[-1].index and hppc.time_s[b - 1] - hppc.time_s[a] > RECHARGE_S:
            stop = a
            break
    ends = [p.index + 1 for p in points[1:]] + [stop]
    ranges = []
    for point, next_rest in zip(points, ends, strict=True):
        start = point.index
        current = hppc.current_a[start:next_rest]
        if not np.any(current > PULSE_A):
            continue
        end = next_rest
        for a, b in _runs(current < -PULSE_A):
            long_step = hppc.time_s[start + b - 1] - hppc.time_s[start + a] > STEP_S
            if long_step and hppc.voltage_v[start + a : start + b].min() <= CUTOFF_V + 0.01:
                end = start + a
                break
        ranges.append((start, end))
    return ranges


def longest_rest_s(window: Measurement) -> float:
    """The longest time without current in a window, in seconds."""
    rests = _runs(np.abs(window.current_a) < REST_CURRENT_A)
    return max((float(window.time_s[b - 1] - window.time_s[a]) for a, b in rests), default=0.0)


def _design(dt: Array, current: Array, tau1: float, tau2: float) -> Array:
    ones = np.ones_like(current)
    u1 = rc_response(dt, current, ones, tau1 * ones)
    u2 = rc_response(dt, current, ones, tau2 * ones)
    return np.column_stack((current, u1, u2))


def fit_window(
    window: Measurement,
    ocv: OcvCurve,
    charge_offset_ah: float,
    charge_transfer: bool = True,
    slope_correction: bool = True,
) -> LevelFit:
    """Fit the parameters to one window of the HPPC test.

    With charge_transfer=False the Butler-Volmer term is left out (a plain two-RC circuit, the
    usual textbook model); i0 is then reported as NO_CHARGE_TRANSFER_A, a current so large that
    the term contributes nothing. slope_correction=False leaves out the straight-line
    correction of the open-circuit voltage, as the first version of the model did
    (tools/compare_variants.py).
    """
    q = charge_offset_ah + window.charge_removed_ah
    target = window.voltage_v - ocv(q)
    dt = np.diff(window.time_s)
    current = window.current_a
    temperature = window.temperature_c
    flowing = np.abs(current) > PULSE_A
    # The slope correction enters as two non-negative columns of opposite sign, so that it may
    # take either sign while the resistances stay non-negative.
    dq = (q - q[0])[:, None]
    correction = np.hstack((dq, -dq)) if slope_correction else np.zeros((len(q), 0))

    def solve(log_theta: Array) -> tuple[Array, Array]:
        tau1, tau2 = np.exp(log_theta[:2])
        rhs = target
        if charge_transfer:
            i0 = np.full_like(current, np.exp(log_theta[2]))
            rhs = target - charge_transfer_v(current, temperature, i0)
        design = np.hstack((_design(dt, current, tau1, tau2), correction))
        coefficients, _ = nnls(design, rhs)
        return coefficients[:3], design @ coefficients - rhs

    bounds = [TAU1_S, TAU2_S, I0_A] if charge_transfer else [TAU1_S, TAU2_S]
    lower, upper = np.log([b[0] for b in bounds]), np.log([b[1] for b in bounds])
    starts = STARTS if charge_transfer else sorted({s[:2] for s in STARTS})

    def residual_of(log_theta: Array) -> Array:
        return solve(log_theta)[1]

    best = None
    for start in starts:
        result = least_squares(residual_of, np.log(start), bounds=(lower, upper), x_scale=1.0)
        if best is None or result.cost < best.cost:
            best = result
    if best is None:  # pragma: no cover - STARTS is a non-empty constant
        raise RuntimeError("no starting point")
    resistances, residual = solve(best.x)
    tau1, tau2 = np.exp(best.x[:2])
    i0 = float(np.exp(best.x[2])) if charge_transfer else NO_CHARGE_TRANSFER_A
    values = dict(
        zip(
            PARAMETERS,
            (resistances[0], resistances[1], tau1, resistances[2], tau2, i0),
            strict=True,
        )
    )
    return LevelFit(
        charge_ah=float(q[0]),
        temperature_c=float(np.mean(temperature[flowing])),
        values={k: float(v) for k, v in values.items()},
        rms_v=float(np.sqrt(np.mean(residual**2))),
        pulse_rms_v=float(np.sqrt(np.mean(residual[flowing] ** 2))),
        samples=len(window),
        longest_rest_s=longest_rest_s(window),
    )


def fit_temperature(
    hppc: Measurement,
    ocv: OcvCurve,
    points: list[RestPoint],
    charge_transfer: bool = True,
    slope_correction: bool = True,
) -> list[LevelFit]:
    """Fit every state of charge of one HPPC test."""
    q = hppc.charge_removed_ah
    return [
        fit_window(hppc.window(a, b), ocv, float(q[a]), charge_transfer, slope_correction)
        for a, b in windows(hppc, points)
    ]

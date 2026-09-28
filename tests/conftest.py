"""Shared fixtures: synthetic tests produced by a cell with known parameters."""

from __future__ import annotations

import numpy as np
import pytest

from celllab.ecm import (
    PARAMETERS,
    CellModel,
    TemperatureTable,
    charge_transfer_v,
    rc_response,
)
from celllab.measurements import Measurement
from celllab.model_file import MODEL_FILE, load_model
from celllab.ocv import OcvCurve

RAW_DATA = MODEL_FILE.parent / "raw"
TRUE = {
    "r0_ohm": 0.02,
    "r1_ohm": 0.006,
    "tau1_s": 4.0,
    "r2_ohm": 0.03,
    "tau2_s": 150.0,
    "i0_a": 1.5,
}


def linear_ocv(top_v: float = 4.2, slope_v_per_ah: float = 0.4, span_ah: float = 3.0) -> OcvCurve:
    q = np.linspace(0.0, span_ah, 601)
    return OcvCurve(q, top_v - slope_v_per_ah * q)


def constant_table(
    temperature_c: float, values: dict[str, float], ocv: OcvCurve
) -> TemperatureTable:
    q = np.array([0.0, 1.5, 3.0])
    return TemperatureTable(
        ambient_c=temperature_c,
        temperature_c=temperature_c,
        ocv=ocv,
        charge_ah=q,
        values={name: np.full(3, values[name]) for name in PARAMETERS},
    )


def pulse_train(
    ocv: OcvCurve, values: dict[str, float], temperature_c: float = 25.0, offset_ah: float = 0.5
) -> Measurement:
    """An HPPC-like sequence of pulses and rests, with the voltage of a known cell."""
    segments = [(0.0, 10.0, 0.1)]
    for amp in (-3.0, -6.0, -12.0, -18.0):
        segments += [(amp, 10.0, 0.1), (0.0, 40.0, 0.1), (-amp / 2, 10.0, 0.1), (0.0, 600.0, 2.0)]
    segments += [(-0.9, 300.0, 1.0), (0.0, 3600.0, 10.0)]
    times, currents = [0.0], [0.0]
    for amp, duration, step in segments:
        n = round(duration / step)
        times += [times[-1] + step * (k + 1) for k in range(n)]
        currents += [amp] * n
    t = np.array(times)
    i = np.array(currents)
    temp = np.full_like(t, temperature_c)
    dt = np.diff(t)
    q = offset_ah - np.concatenate(([0.0], np.cumsum(dt * (i[1:] + i[:-1]) / 2))) / 3600
    ones = np.ones_like(i)
    v = (
        ocv(q)
        + values["r0_ohm"] * i
        + charge_transfer_v(i, temp, np.full_like(i, values["i0_a"]))
        + rc_response(dt, i, values["r1_ohm"] * ones, values["tau1_s"] * ones)
        + rc_response(dt, i, values["r2_ohm"] * ones, values["tau2_s"] * ones)
    )
    return Measurement("synthetic", t, v, i, temp)


@pytest.fixture
def true_values() -> dict[str, float]:
    return dict(TRUE)


@pytest.fixture(scope="session")
def model() -> CellModel:
    return load_model()


@pytest.fixture(scope="session")
def linear_model() -> CellModel:
    return load_model("linear")


raw = pytest.mark.skipif(
    not any(RAW_DATA.rglob("*.mat")) if RAW_DATA.exists() else True,
    reason="raw data not downloaded (python tools/fetch_dataset.py)",
)

"""Checking the model against the drive-cycle tests, which the identification never sees.

Each drive-cycle test starts from a full cell that has rested at the chamber temperature. The
model is given the measured current and the measured cell temperature, starts from rest with
nothing removed, and predicts the terminal voltage; the prediction is compared with the measured
voltage over the whole test, sample by sample, the rest at its end included.

The tests are split in two. The choices made after a first run of the model (the slope
correction and the identifiability rule of identify.py) were compared on the development set,
the Mixed1-4 cycles, alone; the test set, the other cycles, was run only with the final model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from celllab.catalog import DatasetFile
from celllab.ecm import CellModel, Simulation, simulate_current
from celllab.measurements import Measurement, read_mat

DEVELOPMENT = ("Mixed1", "Mixed2", "Mixed3", "Mixed4")


@dataclass(frozen=True)
class CycleResult:
    folder: str
    ambient_c: float
    kind: str
    split: str  # "development" or "test"
    file: str
    duration_h: float
    charge_removed_ah: float
    temperature_min_c: float
    temperature_max_c: float
    rms_mv: float
    mean_abs_mv: float
    p95_abs_mv: float
    max_abs_mv: float


def errors_mv(simulation: Simulation, measurement: Measurement) -> np.ndarray:
    return np.asarray((simulation.voltage_v - measurement.voltage_v) * 1e3)


def run(model: CellModel, test: DatasetFile) -> tuple[CycleResult, Measurement, Simulation]:
    """Simulate one drive-cycle test and compare it with the measurement."""
    measured = read_mat(test.path)
    simulated = simulate_current(model, measured.time_s, measured.current_a, measured.temperature_c)
    err = np.abs(errors_mv(simulated, measured))
    result = CycleResult(
        folder=test.folder,
        ambient_c=test.ambient_c,
        kind=test.kind,
        split="development" if test.kind in DEVELOPMENT else "test",
        file=test.path.name,
        duration_h=float(measured.time_s[-1] / 3600),
        charge_removed_ah=float(simulated.charge_ah[-1]),
        temperature_min_c=float(measured.temperature_c.min()),
        temperature_max_c=float(measured.temperature_c.max()),
        rms_mv=float(np.sqrt(np.mean(err**2))),
        mean_abs_mv=float(np.mean(err)),
        p95_abs_mv=float(np.percentile(err, 95)),
        max_abs_mv=float(np.max(err)),
    )
    return result, measured, simulated

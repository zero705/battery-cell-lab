"""Checking the model against the drive-cycle tests, which the identification never sees.

Each drive-cycle test starts from a full cell that has rested at the chamber temperature. The
model is given the measured current and the measured cell temperature, starts from rest with
nothing removed, and predicts the terminal voltage; the prediction is compared with the measured
voltage over the whole test, sample by sample, the rest at its end included.

The tests are split in two. The choices made after a first run of the model (the slope
correction and the identifiability rule of identify.py) were compared on the development set,
the Mixed1-4 cycles, alone; the test set, the other cycles, was run only with the final model.

Besides the error over the whole test, each result says where the error sits: while the cell
charges (regenerative braking) or discharges, and at the end of discharge, the last tenth of
the charge the test removes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from celllab.catalog import DatasetFile
from celllab.ecm import CellModel, Simulation, simulate_current
from celllab.measurements import Array, Measurement, read_mat

DEVELOPMENT = ("Mixed1", "Mixed2", "Mixed3", "Mixed4")
FLOWING_A = 0.3  # a current above this, either way, counts as charging or discharging
END_OF_DISCHARGE = 0.9  # the end of discharge starts at this share of the most charge removed


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
    charging_time_share: float  # of the samples
    charging_error_share: float  # of the squared error
    mean_charging_mv: float  # mean error (model - measured) while charging; 0 if it never does
    mean_discharging_mv: float  # and while discharging
    end_error_share: float  # share of the squared error at the end of discharge
    largest_at_end: bool  # whether the largest error lies at the end of discharge


def errors_mv(simulation: Simulation, measurement: Measurement) -> Array:
    return np.asarray((simulation.voltage_v - measurement.voltage_v) * 1e3)


def end_of_discharge(charge_ah: Array) -> Array:
    """The samples from where the charge removed first reaches END_OF_DISCHARGE of its largest
    value up to that largest value."""
    last = int(np.argmax(charge_ah))
    first = int(np.argmax(charge_ah >= END_OF_DISCHARGE * charge_ah[last]))
    mask = np.zeros(len(charge_ah), dtype=bool)
    mask[first : last + 1] = True
    return mask


def run(model: CellModel, test: DatasetFile) -> tuple[CycleResult, Measurement, Simulation]:
    """Simulate one drive-cycle test and compare it with the measurement."""
    measured = read_mat(test.path)
    simulated = simulate_current(model, measured.time_s, measured.current_a, measured.temperature_c)
    error = errors_mv(simulated, measured)
    err = np.abs(error)
    squared = error**2
    charging = measured.current_a > FLOWING_A
    discharging = measured.current_a < -FLOWING_A
    end = end_of_discharge(simulated.charge_ah)
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
        rms_mv=float(np.sqrt(np.mean(squared))),
        mean_abs_mv=float(np.mean(err)),
        p95_abs_mv=float(np.percentile(err, 95)),
        max_abs_mv=float(np.max(err)),
        charging_time_share=float(np.mean(charging)),
        charging_error_share=float(squared[charging].sum() / squared.sum()),
        mean_charging_mv=float(np.mean(error[charging])) if charging.any() else 0.0,
        mean_discharging_mv=float(np.mean(error[discharging])) if discharging.any() else 0.0,
        end_error_share=float(squared[end].sum() / squared.sum()),
        largest_at_end=bool(end[int(np.argmax(err))]),
    )
    return result, measured, simulated

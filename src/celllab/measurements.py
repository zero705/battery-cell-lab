"""Reading the McMaster LG 18650HG2 test files.

Each MATLAB file holds one test as a struct ``meas`` with the columns the dataset's readme
describes: Time (s), Voltage (V, sense leads welded to the terminals), Current (A, positive when
charging), Ah, Wh, Power (W) and Battery_Temp_degC (case temperature). What the raw files need,
found by checking all 206 of them (tools/audit_dataset.py):

- In the 205 readable files, 5,751 rows in 176 files repeat the previous time stamp; 5,683 of
  them repeat the values too, the rest differ by at most 0.2 mV and 3 mA. The first row of each
  repeated time is kept.
- The Ah column is reset during some tests, so the charge moved is integrated from the current.
- The Wh column holds small whole numbers that do not follow the energy moved (it reads 3
  throughout the 25 degC UDDS test, which moves 9.4 Wh), so it is not read.
- One file, the LA92 cycle at 10 degC, has time going backwards in four places and three rows
  of NaN; reading it raises an error, and it is left out of the analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import scipy.io

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Measurement:
    """One test, in the dataset's own units and sign convention (current positive on charge)."""

    name: str
    time_s: Array
    voltage_v: Array
    current_a: Array
    temperature_c: Array

    def __post_init__(self) -> None:
        n = len(self.time_s)
        for field in ("voltage_v", "current_a", "temperature_c"):
            if len(getattr(self, field)) != n:
                raise ValueError(f"{self.name}: {field} has a different length than time_s")
        if n and np.any(np.diff(self.time_s) <= 0):
            raise ValueError(f"{self.name}: time must increase strictly")

    def __len__(self) -> int:
        return len(self.time_s)

    @property
    def charge_removed_ah(self) -> Array:
        """Charge taken out of the cell since the first sample, in Ah (trapezoid rule)."""
        return charge_removed_ah(self.time_s, self.current_a)

    def window(self, start: int, stop: int) -> Measurement:
        """The samples start..stop-1, as a measurement of its own."""
        return Measurement(
            self.name,
            self.time_s[start:stop],
            self.voltage_v[start:stop],
            self.current_a[start:stop],
            self.temperature_c[start:stop],
        )


def charge_removed_ah(time_s: Array, current_a: Array) -> Array:
    """Cumulative charge removed (discharge positive), in Ah, by the trapezoid rule."""
    if len(time_s) == 0:
        return np.zeros(0)
    steps = np.diff(time_s) * (current_a[1:] + current_a[:-1]) / 2
    return -np.concatenate(([0.0], np.cumsum(steps))) / 3600


def read_mat(path: Path) -> Measurement:
    """Read one test file. Rows that repeat the previous time stamp are dropped.

    Raises ValueError if time goes backwards or a value is missing: such a file is not used.
    """
    struct = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)["meas"]
    columns = {
        "time": struct.Time,
        "voltage": struct.Voltage,
        "current": struct.Current,
        "temperature": struct.Battery_Temp_degC,
    }
    data = {
        name: np.atleast_1d(np.asarray(values, dtype=float)) for name, values in columns.items()
    }
    for name, values in data.items():
        if np.isnan(values).any():
            raise ValueError(f"{path.name}: {name} has missing values")
    time = data["time"]
    if np.any(np.diff(time) < 0):
        raise ValueError(f"{path.name}: time goes backwards")
    keep = np.concatenate(([True], np.diff(time) > 0))
    return Measurement(
        name=path.stem,
        time_s=time[keep],
        voltage_v=data["voltage"][keep],
        current_a=data["current"][keep],
        temperature_c=data["temperature"][keep],
    )

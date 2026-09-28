"""Reading the test files, and the charge count."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scipy.io

from celllab.measurements import Measurement, charge_removed_ah, read_mat


def _write(path: Path, **columns: object) -> Path:
    n = len(columns["Time"])  # type: ignore[arg-type]
    meas = {
        "Time": columns["Time"],
        "TimeStamp": np.array(["t"] * n, dtype=object),
        "Voltage": columns.get("Voltage", np.full(n, 3.7)),
        "Current": columns.get("Current", np.zeros(n)),
        "Ah": np.zeros(n),
        "Wh": np.full(n, 3, dtype=np.uint8),
        "Power": np.zeros(n),
        "Battery_Temp_degC": columns.get("Battery_Temp_degC", np.full(n, 25.0)),
    }
    scipy.io.savemat(path, {"meas": meas})
    return path


def test_charge_count_of_a_constant_current() -> None:
    t = np.arange(0.0, 3601.0, 10.0)
    q = charge_removed_ah(t, np.full_like(t, -1.5))
    assert q[-1] == pytest.approx(1.5)
    assert charge_removed_ah(np.zeros(0), np.zeros(0)).size == 0


def test_charge_count_uses_the_trapezoid_rule() -> None:
    t = np.array([0.0, 3600.0])
    assert charge_removed_ah(t, np.array([0.0, -2.0]))[-1] == pytest.approx(1.0)


def test_read_mat_keeps_the_first_of_repeated_times(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "x.mat",
        Time=np.array([0.0, 0.1, 0.1, 0.2]),
        Voltage=np.array([4.0, 3.9, 3.8, 3.7]),
        Current=np.array([0.0, -1.0, -1.0, -1.0]),
    )
    m = read_mat(path)
    assert m.name == "x"
    assert m.time_s.tolist() == [0.0, 0.1, 0.2]
    assert m.voltage_v.tolist() == [4.0, 3.9, 3.7]
    assert len(m) == 3


def test_read_mat_refuses_time_going_back(tmp_path: Path) -> None:
    path = _write(tmp_path / "x.mat", Time=np.array([0.0, 1.0, 0.5]))
    with pytest.raises(ValueError, match="backwards"):
        read_mat(path)


def test_read_mat_refuses_missing_values(tmp_path: Path) -> None:
    path = _write(tmp_path / "x.mat", Time=np.array([0.0, 1.0]), Voltage=np.array([4.0, np.nan]))
    with pytest.raises(ValueError, match="voltage has missing values"):
        read_mat(path)


def test_measurement_is_checked() -> None:
    t = np.array([0.0, 1.0])
    with pytest.raises(ValueError, match="different length"):
        Measurement("m", t, np.ones(3), np.ones(2), np.ones(2))
    with pytest.raises(ValueError, match="increase strictly"):
        Measurement("m", np.array([0.0, 0.0]), np.ones(2), np.ones(2), np.ones(2))


def test_window_is_a_measurement_of_its_own() -> None:
    t = np.arange(10.0)
    m = Measurement("m", t, t + 1, t + 2, t + 3)
    w = m.window(2, 5)
    assert w.time_s.tolist() == [2.0, 3.0, 4.0]
    assert w.temperature_c.tolist() == [5.0, 6.0, 7.0]

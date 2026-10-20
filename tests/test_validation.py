"""The validation runs, and data/validation.json holds what the model computes."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
import scipy.io
from conftest import raw

from celllab import catalog, validation
from celllab.catalog import DatasetFile
from celllab.ecm import CellModel, simulate_current
from celllab.measurements import charge_removed_ah
from celllab.model_file import MODEL_FILE

VALIDATION = MODEL_FILE.parent / "validation.json"


def _synthetic_cycle(model: CellModel, path: Path, current: np.ndarray, bump_at: int) -> None:
    """A drive-cycle file whose voltage the model itself produced, plus 10 mV, and 5 mV more
    at one sample."""
    t = np.arange(0.0, 0.5 * len(current), 0.5)
    temperature = np.full_like(t, 25.0)
    voltage = simulate_current(model, t, current, temperature).voltage_v + 0.010
    voltage[bump_at] += 0.005
    n = len(t)
    scipy.io.savemat(
        path,
        {
            "meas": {
                "Time": t,
                "TimeStamp": np.array(["t"] * n, dtype=object),
                "Voltage": voltage,
                "Current": current,
                "Ah": np.zeros(n),
                "Wh": np.zeros(n, dtype=np.uint8),
                "Power": voltage * current,
                "Battery_Temp_degC": temperature,
            }
        },
    )


def test_run_compares_prediction_and_measurement(model: CellModel, tmp_path: Path) -> None:
    path = tmp_path / "01-01-18_00.00 1_UDDS_25degC_LGHG2.mat"
    t = np.arange(0.0, 1800.0, 0.5)
    current = 1.0 - 2.0 * (1 + np.sin(t / 30.0))  # from 1 A of charge to 3 A of discharge
    end = int(np.argmax(charge_removed_ah(t, current)))  # where the most charge is removed
    _synthetic_cycle(model, path, current, bump_at=end)
    result, measured, simulated = validation.run(model, DatasetFile("25degC", "UDDS", path))
    assert result.split == "test"
    assert result.rms_mv == pytest.approx(10.0, abs=0.01)
    assert result.max_abs_mv == pytest.approx(15.0, abs=1e-6)
    # The error is the model minus the measurement: here 10 mV low everywhere.
    assert result.mean_charging_mv == pytest.approx(-10.0, abs=0.01)
    assert result.mean_discharging_mv == pytest.approx(-10.0, abs=0.01)
    charging = measured.current_a > validation.FLOWING_A
    assert result.charging_time_share == pytest.approx(np.mean(charging))
    assert result.charging_error_share == pytest.approx(np.mean(charging), abs=0.01)
    assert result.largest_at_end
    assert result.duration_h == pytest.approx(measured.time_s[-1] / 3600)
    assert result.charge_removed_ah == pytest.approx(simulated.charge_ah[-1])
    assert result.temperature_min_c == result.temperature_max_c == 25.0
    mixed = validation.run(model, DatasetFile("25degC", "Mixed2", path))[0]
    assert mixed.split == "development"


def test_a_test_that_never_charges(model: CellModel, tmp_path: Path) -> None:
    path = tmp_path / "01-01-18_00.00 1_UDDS_25degC_LGHG2.mat"
    _synthetic_cycle(model, path, np.full(600, -2.0), bump_at=0)
    result = validation.run(model, DatasetFile("25degC", "UDDS", path))[0]
    assert result.charging_time_share == result.charging_error_share == 0.0
    assert result.mean_charging_mv == 0.0
    assert not result.largest_at_end  # the bump is at the start


def test_end_of_discharge_is_the_last_tenth_of_the_charge_removed() -> None:
    q = np.array([0.0, 0.3, 0.6, 0.91, 0.89, 0.95, 1.0, 1.0, 0.98])
    mask = validation.end_of_discharge(q)
    assert mask.tolist() == [False, False, False, True, True, True, True, False, False]


def test_validation_file_lists_every_usable_test_once() -> None:
    data = json.loads(VALIDATION.read_text(encoding="utf-8"))
    expected = {(c.folder, c.kind) for c in catalog.drive_cycles()}
    for rows in data["variants"].values():
        assert {(r["folder"], r["kind"]) for r in rows} == expected
        assert len(rows) == len(expected) == 62
        for r in rows:
            assert r["split"] == ("development" if r["kind"] in validation.DEVELOPMENT else "test")
            assert 0 < r["rms_mv"] <= r["max_abs_mv"]
            assert 0 < r["charging_time_share"] < 1
            assert 0 < r["charging_error_share"] < 1
            assert 0 < r["end_error_share"] < 1
    assert {(e["folder"], e["kind"]) for e in data["excluded"]} == set(catalog.EXCLUDED)


def test_every_test_has_a_trace_and_no_other_trace_is_kept() -> None:
    traces = {p.name for p in (MODEL_FILE.parent / "traces").glob("*.csv.gz")}
    assert traces == {f"{c.folder}_{c.kind}.csv.gz" for c in catalog.drive_cycles()}


@raw
@pytest.mark.parametrize(
    ("folder", "kind"), [("25degC", "UDDS"), ("n20degC", "US06"), ("n10degC", "Mixed2")]
)
def test_validation_file_matches_a_fresh_run(model: CellModel, folder: str, kind: str) -> None:
    data = json.loads(VALIDATION.read_text(encoding="utf-8"))
    stored = next(
        r for r in data["variants"]["charge_transfer"] if (r["folder"], r["kind"]) == (folder, kind)
    )
    fresh = asdict(validation.run(model, catalog.find(folder, kind))[0])
    assert set(stored) == set(fresh)
    for name, value in fresh.items():
        if isinstance(value, float):
            assert stored[name] == pytest.approx(value, rel=1e-4, abs=1e-9), name
        else:
            assert stored[name] == value, name

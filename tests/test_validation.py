"""The validation runs, and data/validation.json holds what the model computes."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import scipy.io
from conftest import raw

from celllab import catalog, validation
from celllab.catalog import DatasetFile
from celllab.ecm import CellModel, simulate_current
from celllab.model_file import MODEL_FILE

VALIDATION = MODEL_FILE.parent / "validation.json"


def _synthetic_cycle(model: CellModel, path: Path) -> None:
    """A drive-cycle file whose voltage the model itself produced, plus 10 mV."""
    t = np.arange(0.0, 1800.0, 0.5)
    current = -2.0 * (1 + np.sin(t / 30.0))
    temperature = np.full_like(t, 25.0)
    voltage = simulate_current(model, t, current, temperature).voltage_v + 0.010
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
    _synthetic_cycle(model, path)
    result, measured, simulated = validation.run(model, DatasetFile("25degC", "UDDS", path))
    assert result.split == "test"
    assert result.rms_mv == pytest.approx(10.0, abs=1e-6)
    assert result.max_abs_mv == pytest.approx(10.0, abs=1e-6)
    assert result.duration_h == pytest.approx(measured.time_s[-1] / 3600)
    assert result.charge_removed_ah == pytest.approx(simulated.charge_ah[-1])
    assert result.temperature_min_c == result.temperature_max_c == 25.0
    mixed = validation.run(model, DatasetFile("25degC", "Mixed2", path))[0]
    assert mixed.split == "development"


def test_validation_file_lists_every_usable_test_once() -> None:
    data = json.loads(VALIDATION.read_text(encoding="utf-8"))
    expected = {(c.folder, c.kind) for c in catalog.drive_cycles()}
    for rows in data["variants"].values():
        assert {(r["folder"], r["kind"]) for r in rows} == expected
        assert len(rows) == len(expected) == 63
        for r in rows:
            assert r["split"] == ("development" if r["kind"] in validation.DEVELOPMENT else "test")
            assert 0 < r["rms_mv"] <= r["max_abs_mv"]
    assert {(e["folder"], e["kind"]) for e in data["excluded"]} == set(catalog.EXCLUDED)


def test_every_test_has_a_trace() -> None:
    for c in catalog.drive_cycles():
        assert (MODEL_FILE.parent / "traces" / f"{c.folder}_{c.kind}.csv.gz").exists()


@raw
@pytest.mark.parametrize(("folder", "kind"), [("25degC", "UDDS"), ("n20degC", "US06")])
def test_validation_file_matches_a_fresh_run(model: CellModel, folder: str, kind: str) -> None:
    data = json.loads(VALIDATION.read_text(encoding="utf-8"))
    stored = next(
        r for r in data["variants"]["charge_transfer"] if (r["folder"], r["kind"]) == (folder, kind)
    )
    fresh = validation.run(model, catalog.find(folder, kind))[0]
    assert stored["rms_mv"] == pytest.approx(fresh.rms_mv, rel=1e-4)
    assert stored["max_abs_mv"] == pytest.approx(fresh.max_abs_mv, rel=1e-4)

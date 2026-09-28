"""The documents say what the data and the model say."""

from __future__ import annotations

import gzip
import io
import json
import re
import statistics
import sys
from pathlib import Path

import numpy as np
import pytest

from celllab import catalog, identify, lab
from celllab.model_file import read

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import update_docs  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = README + (ROOT / "docs" / "method.md").read_text(encoding="utf-8")


def _validation(variant: str = "charge_transfer") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(
        (ROOT / "data" / "validation.json").read_text(encoding="utf-8")
    )["variants"][variant]
    return rows


@pytest.mark.parametrize("name", update_docs.DOCUMENTS)
def test_generated_tables_are_up_to_date(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert update_docs.refresh(text) == text, f"run python tools/update_docs.py ({name})"
    assert "<!-- generated:" in text


def test_unknown_block_is_refused() -> None:
    with pytest.raises(KeyError, match="unknown"):
        update_docs.refresh("<!-- generated: nothing -->\nx\n<!-- end generated -->")


def test_update_docs_check_mode_reports_nothing_stale() -> None:
    assert update_docs.main(["--check"]) == 0


def test_headline_numbers() -> None:
    rms = [float(r["rms_mv"]) for r in _validation()]  # type: ignore[arg-type]
    assert f"median of **{statistics.median(rms):.0f} mV RMS**" in README
    assert f"**{len(rms)} drive-cycle tests" in README
    test = [r for r in _validation() if r["split"] == "test"]
    assert f"the other {len(test)} tests (test set)" in README
    worst_linear = max(
        float(r["rms_mv"])  # type: ignore[arg-type]
        for r in _validation("linear")
        if r["ambient_c"] == -20.0
    )
    worst = max(
        float(r["rms_mv"])  # type: ignore[arg-type]
        for r in _validation()
        if r["ambient_c"] == -20.0
    )
    assert f"from {worst_linear:.0f} to {worst:.0f} mV" in README


def test_cold_charging_errors() -> None:
    charging, discharging = [], []
    for c in catalog.drive_cycles():
        if c.folder != "n20degC":
            continue
        raw = gzip.decompress(
            (ROOT / "data" / "traces" / f"{c.folder}_{c.kind}.csv.gz").read_bytes()
        )
        t = np.genfromtxt(io.BytesIO(raw), delimiter=",", names=True)
        error = (t["charge_transfer_v"] - t["measured_v"]) * 1e3
        charging.append(error[t["current_a"] > 0.2].mean())
        discharging.append((c.kind, error[t["current_a"] < -0.2].mean()))
    assert f"{min(charging):.0f} to {max(charging):.0f} mV high" in README
    within = [k for k, e in discharging if abs(e) <= 17]
    assert len(within) == 11
    (odd,) = [e for k, e in discharging if k not in within]
    assert f"US06: {abs(odd):.0f} mV low" in README


def test_method_numbers() -> None:
    model = read()
    assert f"off by {model['ocv_leave_one_out']['rms_mv']:.1f} mV RMS" in README
    assert f"from {len(identify.STARTS)} starting points".replace("12", "twelve") in README
    dropped = sum(
        not lv["identifiable"]
        for e in model["temperatures"]
        for lv in e["variants"]["charge_transfer"]["levels"]
    )
    levels = sum(len(e["variants"]["charge_transfer"]["levels"]) for e in model["temperatures"])
    assert f"({dropped} of {levels})" in README
    assert f"less than {lab.MIN_SHARE * 100:.0f} %" in DOCS


def test_every_link_to_a_repository_file_exists() -> None:
    for text, base in ((README, ROOT), (DOCS, ROOT)):
        for target in re.findall(r"\]\((?!https?://|#)([^)#]+)", text):
            assert (base / target).exists() or (base / "docs" / target).exists(), target

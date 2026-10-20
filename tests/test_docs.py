"""The documents say what the data and the model say.

Every number the README, docs/method.md, docs/data.md and the changelog state is recomputed here
from data/, or checked against the code; those about the raw data are recomputed from it by
tests/test_raw_data.py.
"""

from __future__ import annotations

import itertools
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import REPORT_RESISTANCE_MOHM

from celllab import catalog, identify, lab, validation
from celllab.ecm import FARADAY, GAS_CONSTANT, KELVIN, CellModel, charge_transfer_v
from celllab.model_file import read

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import update_docs  # noqa: E402
import validate_model  # noqa: E402

import streamlit_app  # noqa: E402


def _flat(name: str) -> str:
    """A document with its line breaks as spaces, so that a phrase may span lines."""
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


README = _flat("README.md")
METHOD = _flat("docs/method.md")
DATA_MD = _flat("docs/data.md")
CHANGELOG = _flat("CHANGELOG.md")
WORDS = {8: "eight", 11: "eleven", 12: "twelve"}
TEMPERATURES = (-20.0, -10.0, 0.0, 10.0, 25.0, 40.0)


def _json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
    return data


def _validation(variant: str = "charge_transfer") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _json("validation.json")["variants"][variant]
    return rows


def _rms(rows: list[dict[str, Any]], ambient_c: float | None = None) -> list[float]:
    return [float(r["rms_mv"]) for r in rows if ambient_c is None or r["ambient_c"] == ambient_c]


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
    rms = _rms(_validation())
    median = statistics.median(rms)
    assert (
        f"Over all {len(rms)} tests the median error is **{median:.0f} mV RMS**. That is less "
        "than 1 % of the cell's nominal voltage of 3.6 V"
    ) in README
    assert median / 3600 < 0.01
    assert f"checked it on {len(rms)} drive-cycle tests from -20 to 40 °C" in README
    test = [r for r in _validation() if r["split"] == "test"]
    assert f"The other {len(test)} tests (test set) I ran once at the end" in README
    worst_linear = max(_rms(_validation("linear"), -20.0))
    worst = max(_rms(_validation(), -20.0))
    assert f"and the worst test from {worst_linear:.0f} to {worst:.0f} mV" in README
    assert validation.DEVELOPMENT == ("Mixed1", "Mixed2", "Mixed3", "Mixed4")
    assert "looking only at the Mixed1-4 cycles (development set)" in README


def test_what_the_charge_transfer_term_changes() -> None:
    def medians(t_c: float) -> tuple[float, float]:
        return (
            statistics.median(_rms(_validation(), t_c)),
            statistics.median(_rms(_validation("linear"), t_c)),
        )

    warm = max(abs(ct - lin) for ct, lin in map(medians, (0.0, 10.0, 25.0, 40.0)))
    assert f"From 0 °C up the term changes the median by at most {warm:.1f} mV" in README
    for t_c in (-20.0, -10.0):
        ct, lin = medians(t_c)
        assert ct < lin
    ct, lin = medians(-20.0)
    assert f"at -20 °C the median goes from {lin:.1f} to {ct:.1f} mV" in README


def test_where_the_error_comes_from() -> None:
    rows = _validation()
    warm = [r for r in rows if r["ambient_c"] >= 10]
    at_end = sum(r["largest_at_end"] for r in warm)
    assert (
        f"In {at_end} of the {len(warm)} tests the largest error is in the last tenth of the "
        "charge removed"
    ) in README
    cold = [r for r in rows if r["ambient_c"] == -20]
    charging = [r["mean_charging_mv"] for r in cold]
    assert min(charging) > 0
    assert (
        f"In all {WORDS[len(cold)]} -20 °C tests the model's voltage is too high while the cell "
        f"is being charged by regenerative braking, by {min(charging):.0f} to "
        f"{max(charging):.0f} mV on average"
    ) in README
    others = [r["mean_discharging_mv"] for r in cold if r["kind"] != "US06"]
    assert max(abs(e) for e in others) < 20
    assert (
        f"the mean error stays within 20 mV in {WORDS[len(others)]} of the {WORDS[len(cold)]} tests"
    ) in README
    (us06,) = [r["mean_discharging_mv"] for r in cold if r["kind"] == "US06"]
    assert us06 < -20
    assert f"US06 is the exception, {abs(us06):.0f} mV low" in README
    time = statistics.median(r["charging_time_share"] for r in cold)
    error = statistics.median(r["charging_error_share"] for r in cold)
    assert (
        f"Charging is only {100 * time:.0f} % of the time at -20 °C, but {100 * error:.0f} % of "
        "the squared error comes from it"
    ) in README
    for t_c in TEMPERATURES:
        at_t = [r for r in rows if r["ambient_c"] == t_c]
        assert max(at_t, key=lambda r: r["rms_mv"])["kind"] == "US06", t_c
    assert "has the largest error at every temperature" in README
    low = [-r["mean_discharging_mv"] for r in rows if r["kind"] == "US06"]
    assert min(low) > 0
    assert (
        f"too low while the cell discharges, by {min(low):.0f} to {max(low):.0f} mV on average"
    ) in README


def test_cross_checks() -> None:
    figures = ", ".join(f"{v:.1f}" for v in list(REPORT_RESISTANCE_MOHM.values())[:-1])
    assert f"{figures} and {REPORT_RESISTANCE_MOHM['40degC']:.1f} mΩ from -20 to 40 °C" in README
    assert f"{figures} and {REPORT_RESISTANCE_MOHM['40degC']:.1f} mΩ from -20 to 40 °C" in METHOD
    measured = streamlit_app.US06_COLD_SHARE_MEASURED  # recomputed by tests/test_raw_data.py
    assert (
        f"the cell gave only {100 * measured:.0f} % of the discharge energy the first cycle "
        "asked for"
    ) in README
    assert f"held the cell to {100 * measured:.0f} % of the first period's" in METHOD
    files = _json("dataset.json")["files"]
    assert f"All {len(files)} files are checked against the SHA-256 hashes" in README
    assert f"I went through all {len(files)} files" in README
    excluded = WORDS[len(catalog.EXCLUDED)]
    assert f"But {excluded} of the drive-cycle tests can't be used" in README
    assert f"{excluded.capitalize()} drive-cycle tests can't be used" in DATA_MD
    assert f"{excluded.capitalize()} unusable drive-cycle tests are left out" in CHANGELOG
    assert f"Download of the McMaster LG 18650HG2 data ({len(files)} files)" in CHANGELOG


def test_the_lab_numbers(model: CellModel) -> None:
    cold = lab.drive(model, lab.load_profiles()["US06"], "US06", -20.0)
    assert cold.cycles_completed == 1.0  # so its share is that of the first period
    share = 100 * cold.share_delivered
    assert f"with the same demand and the same limits, gives {share:.0f} %" in README
    assert f"limits at -20 °C, gives {share:.0f} %" in METHOD
    profiles = lab.load_profiles()
    lower = sum(
        lab.drive(model, profiles[c], c, 40.0).energy_wh
        < lab.drive(model, profiles[c], c, 25.0).energy_wh
        for c in profiles
    )
    assert lower == 3
    assert "a bit less energy than at 25 °C on three of the four cycles" in README
    periods = ", ".join(f"{p} s ({c})" for c, p in list(validate_model.PERIOD_S.items())[:-1])
    assert f"{periods} and 601 s (US06)" in METHOD
    assert validate_model.PERIOD_S["US06"] == 601
    assert lab.DISCHARGE_LIMIT_A[:2] == ((-20.0, 6.0), (-10.0, 12.0))
    assert "discharge current to 6 A at -20 °C and 12 A at -10 °C" in METHOD
    assert lab.REGEN_LIMIT_A == ((-20.0, 1.5), (-10.0, 3.0), (0.0, 3.0), (10.0, 6.0))
    assert "to 1.5 A at -20 °C, 3 A at -10 and 0 °C and 6 A from 10 °C up" in METHOD
    assert f"less than {lab.MIN_SHARE * 100:.0f} %" in METHOD


def test_open_circuit_voltage_numbers() -> None:
    model = read()
    loo = model["ocv_leave_one_out"]
    assert f"predict it from the others, the error is {loo['rms_mv']:.1f} mV RMS" in README
    assert f"(leave one out, {loo['points']} points over the six temperatures)" in METHOD
    assert f"(used) | {loo['rms_mv']:.1f} mV | {loo['max_abs_mv']:.0f} mV |" in METHOD
    points = [len(e["rest_points"]) for e in model["temperatures"]]
    assert f"each of its {min(points) - 1} to {max(points) - 1} steps down" in METHOD
    assert f"only at those {min(points)} to {max(points)} points" in METHOD
    for entry in model["temperatures"]:
        voltage = entry["ocv"]["voltage_v"]
        charge = entry["ocv"]["charge_ah"]
        slopes = [
            (a - b) / (q - p)
            for (a, b), (p, q) in zip(
                itertools.pairwise(voltage), itertools.pairwise(charge), strict=True
            )
        ]
        assert max(range(len(slopes)), key=slopes.__getitem__) == len(slopes) - 1  # at empty


def test_identification_numbers() -> None:
    model = read()
    assert f"from {len(identify.STARTS)} starting points".replace("12", "twelve") in README
    (lo1, hi1), (lo2, hi2), (lo3, hi3) = identify.TAU1_S, identify.TAU2_S, identify.I0_A
    assert (
        f"over tau1 ({lo1:g}-{hi1:g} s), tau2 ({lo2:g}-{hi2:g} s) and i0 ({lo3:g}-{hi3:g} A)"
    ) in METHOD
    levels = [
        (e["ambient_c"], lv)
        for e in model["temperatures"]
        for lv in e["variants"]["charge_transfer"]["levels"]
    ]
    dropped = [lv for _, lv in levels if not lv["identifiable"]]
    assert f"({len(dropped)} of {len(levels)} levels)" in README
    tau2 = [lv["tau2_s"] for lv in dropped]
    assert f"put tau2 at {min(tau2):.0f} to {max(tau2):.0f} s" in METHOD
    used = [(t_c, lv) for t_c, lv in levels if lv["identifiable"]]
    at_bound = [t_c for t_c, lv in used if lv["i0_a"] >= 0.999 * identify.I0_A[1]]
    assert min(at_bound) >= 0
    assert f"in {len(at_bound)} of the {len(used)} levels used, all at 0 °C and above" in METHOD
    # The levels nearest half full, as in the parameter table.
    half = {
        e["ambient_c"]: min(
            (lv for lv in e["variants"]["charge_transfer"]["levels"] if lv["identifiable"]),
            key=lambda lv: abs(lv["charge_ah"] - 1.5),
        )
        for e in model["temperatures"]
    }
    warm = [round(half[t_c]["i0_a"]) for t_c in (10.0, 25.0, 40.0)]
    assert f"i0 rises from {half[-20.0]['i0_a']:.1f} A at -20 °C" in METHOD
    assert f"to {min(warm)} to {max(warm)} A from 10 °C up" in METHOD
    i0, r0 = half[25.0]["i0_a"], half[25.0]["r0_ohm"]
    r_ct = GAS_CONSTANT * (25.0 + KELVIN) / (FARADAY * i0)
    assert f"With i0 = {i0:.1f} A, its value at 25 °C" in METHOD
    assert f"the charge-transfer term is {r_ct * 1e3:.1f} mΩ at small currents" in METHOD
    assert f"against {r0 * 1e3:.1f} mΩ for R0" in METHOD
    # The circuit without the term: below a nanovolt even at 20 A and 50 degC.
    eta = charge_transfer_v(
        np.array([20.0]), np.array([50.0]), np.array([identify.NO_CHARGE_TRANSFER_A])
    )
    assert abs(eta[0]) < 1e-9


def test_development_numbers() -> None:
    development = _json("development.json")
    rows = _validation()
    dev = [r for r in rows if r["split"] == "development"]
    test = [r for r in rows if r["split"] == "test"]
    assert development["development_tests"] == len(dev)
    assert f"The Mixed1-4 cycles ({len(dev)} tests) became the development set" in METHOD
    assert f"The other {len(test)} tests became the test set" in METHOD
    # The final variant of the comparison is the model: the same error on every test.
    both = development["variants"]["both"]["development"]["rms_mv"]
    assert both == {f"{r['folder']}/{r['kind']}": pytest.approx(r["rms_mv"], rel=1e-4) for r in dev}
    levels = [
        lv for e in read()["temperatures"] for lv in e["variants"]["charge_transfer"]["levels"]
    ]
    assert development["variants"]["both"]["levels"] == sum(lv["identifiable"] for lv in levels)
    assert development["variants"]["first"]["levels"] == len(levels)
    first = development["first_on_every_test"]
    assert first["tests"] == len(rows)
    assert (
        f"I ran it once on all {len(rows)} tests. Its median error was {first['median_mv']:.1f} mV"
        in METHOD
    )
    assert (
        f"in the median test, {100 * first['rest_after_share']:.0f} % of its squared error lies "
        f"in the rest after the drive and {100 * first['end_of_discharge_share']:.0f} % in the "
        "last tenth of the discharge"
    ) in METHOD
    median_dev = statistics.median(_rms(dev))
    median_test = statistics.median(_rms(test))
    assert median_test <= median_dev
    assert f"(median {median_test:.1f} against {median_dev:.1f} mV)" in METHOD
    core = development["core_temperature"]
    assert core["offsets_c"] == [0.0, 2.0, 4.0, 6.0]
    m = core["median_mv"]
    assert m == sorted(m)
    assert (
        f"plus 2, 4 or 6 °C raises the median error of the {WORDS[core['tests']]} -20 °C tests"
        in METHOD
    )
    assert f"from {m[0]:.1f} mV to {m[1]:.1f}, {m[2]:.1f} and {m[3]:.1f} mV" in METHOD


def test_counts_in_every_document() -> None:
    tests = len(_validation())
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f"checked on {tests} drive-cycle tests" in pyproject
    assert re.search(r"^fail_under = 100$", pyproject, re.MULTILINE)  # the "100 %" of the docs
    assert "Tests for the model, the app and every number in the docs (100 % coverage)" in (
        CHANGELOG
    )
    assert f"Validation on {tests} drive-cycle tests" in CHANGELOG
    assert f"That leaves {tests} drive-cycle tests" in DATA_MD
    assert f"which leaves {tests} tests" in README
    size_mb = sum(f["size"] for f in _json("dataset.json")["files"]) / 1e6
    files = len(_json("dataset.json")["files"])
    assert f"# {files} files, {size_mb:.0f} MB, each checked" in README


def _anchors(path: Path) -> set[str]:
    """The anchors GitHub gives the headings of a Markdown file."""
    headings = re.findall(r"^#+ (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h).strip().lower().replace(" ", "-") for h in headings}


def test_every_link_to_a_repository_file_exists() -> None:
    for name in ("README.md", "docs/method.md", "docs/data.md", "SECURITY.md", "CHANGELOG.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        base = (ROOT / name).parent
        for target, anchor in re.findall(r"\]\((?!https?://|#)([^)#]+)(?:#([^)]+))?\)", text):
            assert (base / target).exists(), f"{name}: {target}"
            if anchor:
                assert anchor in _anchors(base / target), f"{name}: {target}#{anchor}"

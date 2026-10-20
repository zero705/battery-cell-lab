"""Rerun the comparisons that chose the model, and write data/development.json.

The first version of the model had neither of the two choices of celllab.identify: the
straight-line correction of the open-circuit voltage within each fit window, and the rule that
leaves out levels whose slow time constant the window cannot show. Its run on every drive-cycle
test showed where its errors lay. The choices were then compared on the development set (the
Mixed1-4 cycles) alone; the test set was run only with the final model (tools/validate_model.py).

This script identifies the model with and without the correction, builds it with and without
the rule, and runs:

- the first version on every test, and where its error sits;
- each of the four combinations on the development set;
- the final model on the -20 degC tests with the measured case temperature raised by 2, 4 and
  6 degC: the check of whether heating of the cell's core explains the error in the cold.

    python tools/compare_variants.py     # about five minutes
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import identify_model  # noqa: E402

from celllab import catalog, validation  # noqa: E402
from celllab.catalog import DatasetFile  # noqa: E402
from celllab.ecm import CellModel, simulate_current  # noqa: E402
from celllab.measurements import read_mat  # noqa: E402
from celllab.model_file import from_data  # noqa: E402

OUT = ROOT / "data" / "development.json"
# name -> (slope correction, identifiability rule)
VARIANTS = {
    "first": (False, False),
    "slope_correction": (True, False),
    "identifiability_rule": (False, True),
    "both": (True, True),
}
CORE_OFFSETS_C = (0.0, 2.0, 4.0, 6.0)


def sig(value: float) -> float:
    return float(f"{value:.5g}")


def rms_of(values: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def run_tests(model: CellModel, tests: list[DatasetFile]) -> dict[str, Any]:
    """Each test's RMS error, and the median and the RMS of those."""
    rms = {f"{t.folder}/{t.kind}": validation.run(model, t)[0].rms_mv for t in tests}
    return {
        "median_mv": sig(statistics.median(rms.values())),
        "rms_of_rms_mv": sig(rms_of(list(rms.values()))),
        "rms_mv": {k: sig(v) for k, v in rms.items()},
    }


def where_the_error_sits(model: CellModel, tests: list[DatasetFile]) -> dict[str, float]:
    """Median over the tests of the share of the squared error at the end of discharge and in
    the rest after the drive."""
    end, after = [], []
    for test in tests:
        _, measured, simulated = validation.run(model, test)
        squared = validation.errors_mv(simulated, measured) ** 2
        q = simulated.charge_ah
        rest = np.arange(len(q)) > int(np.argmax(q))
        end.append(squared[validation.end_of_discharge(q)].sum() / squared.sum())
        after.append(squared[rest].sum() / squared.sum())
    return {
        "end_of_discharge_share": sig(statistics.median(end)),
        "rest_after_share": sig(statistics.median(after)),
    }


def core_temperature(model: CellModel, tests: list[DatasetFile]) -> dict[str, Any]:
    """The -20 degC errors with the measured case temperature raised by each offset."""
    rms: dict[str, list[float]] = {f"{t.folder}/{t.kind}": [] for t in tests}
    for test in tests:
        m = read_mat(test.path)
        for offset in CORE_OFFSETS_C:
            s = simulate_current(model, m.time_s, m.current_a, m.temperature_c + offset)
            rms[f"{test.folder}/{test.kind}"].append(
                float(np.sqrt(np.mean(validation.errors_mv(s, m) ** 2)))
            )
    by_offset = list(zip(*rms.values(), strict=True))
    return {
        "offsets_c": list(CORE_OFFSETS_C),
        "median_mv": [sig(statistics.median(v)) for v in by_offset],
        "rms_of_rms_mv": [sig(rms_of(list(v))) for v in by_offset],
    }


def main() -> None:
    start = time.time()
    fitted = {
        correction: identify_model.build(("charge_transfer",), slope_correction=correction)
        for correction in (False, True)
    }
    models = {
        name: from_data(fitted[correction], identifiable_only=rule)
        for name, (correction, rule) in VARIANTS.items()
    }
    tests = catalog.drive_cycles()
    development = [t for t in tests if t.kind in validation.DEVELOPMENT]
    out: dict[str, Any] = {"development_tests": len(development), "variants": {}}
    for name, (correction, rule) in VARIANTS.items():
        levels = sum(len(t.charge_ah) for t in models[name].tables)
        out["variants"][name] = {
            "slope_correction": correction,
            "identifiability_rule": rule,
            "levels": levels,
            "development": run_tests(models[name], development),
        }
        print(f"{name}: {levels} levels, development {out['variants'][name]['development']}")
    out["first_on_every_test"] = {
        "tests": len(tests),
        **{k: v for k, v in run_tests(models["first"], tests).items() if k != "rms_mv"},
        **where_the_error_sits(models["first"], tests),
    }
    cold = [t for t in tests if t.folder == "n20degC"]
    out["core_temperature"] = {"tests": len(cold), **core_temperature(models["both"], cold)}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} in {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()

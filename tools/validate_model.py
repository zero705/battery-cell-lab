"""Run both model variants through every usable drive-cycle test; write data/validation.json.

Also writes data/traces/, the measured and predicted voltage of every test every 2 s, which the
app plots, and data/profiles.csv, one period of each standard cycle's power demand.

    python tools/validate_model.py
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from celllab import catalog, validation  # noqa: E402
from celllab.measurements import read_mat  # noqa: E402
from celllab.model_file import VARIANTS, load_model  # noqa: E402

DATA = ROOT / "data"
TRACES = DATA / "traces"
TRACE_STEP_S = 2.0
# One period of each standard cycle, in seconds: the lag of the highest peak of the power
# trace's autocorrelation between 300 and 2500 s, in the 40 degC tests (the only temperature
# with all four cycles usable and no limit on regenerative braking). tests/test_profiles.py
# recomputes these from the raw data.
PERIOD_S = {"UDDS": 1370, "HWFET": 766, "LA92": 1438, "US06": 601}
PROFILE_FOLDER = "40degC"


def sig(value: float, digits: int = 5) -> float:
    return float(f"{value:.{digits}g}")


def write_trace(name: str, measured, simulations) -> None:  # type: ignore[no-untyped-def]
    t = np.arange(0.0, measured.time_s[-1], TRACE_STEP_S)
    columns = {
        "time_s": t,
        "current_a": np.interp(t, measured.time_s, measured.current_a),
        "temperature_c": np.interp(t, measured.time_s, measured.temperature_c),
        "measured_v": np.interp(t, measured.time_s, measured.voltage_v),
        **{
            f"{variant}_v": np.interp(t, sim.time_s, sim.voltage_v)
            for variant, sim in simulations.items()
        },
    }
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    formats = {"time_s": "{:.0f}", "current_a": "{:.3f}", "temperature_c": "{:.2f}"}
    for row in zip(*columns.values(), strict=True):
        writer.writerow(
            formats.get(k, "{:.4f}").format(v) for k, v in zip(columns, row, strict=True)
        )
    # mtime=0 keeps the compressed file identical from run to run.
    (TRACES / f"{name}.csv.gz").write_bytes(gzip.compress(buffer.getvalue().encode(), mtime=0))


def write_profiles() -> None:
    rows = {}
    for kind, period in PERIOD_S.items():
        m = read_mat(catalog.find(PROFILE_FOLDER, kind).path)
        t = np.arange(0, period, 1.0)
        rows[kind] = np.interp(t, m.time_s, m.voltage_v * m.current_a)
    length = max(len(v) for v in rows.values())
    with (DATA / "profiles.csv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Power at the cell terminals (W, negative on discharge), one period of each\n")
        f.write(
            f"# cycle, 1 s steps, from the {PROFILE_FOLDER} tests of the McMaster LG 18650HG2\n"
        )
        f.write("# data (CC BY 4.0); see tools/validate_model.py\n")
        f.write("time_s," + ",".join(rows) + "\n")
        for k in range(length):
            cells = [f"{rows[c][k]:.3f}" if k < len(rows[c]) else "" for c in rows]
            f.write(f"{k}," + ",".join(cells) + "\n")


def main() -> None:
    TRACES.mkdir(exist_ok=True)
    models = {variant: load_model(variant) for variant in VARIANTS}
    results: dict[str, list[dict[str, object]]] = {v: [] for v in VARIANTS}
    start = time.time()
    for test in catalog.drive_cycles():
        simulations = {}
        for variant, model in models.items():
            result, measured, simulated = validation.run(model, test)
            row = {k: sig(v) if isinstance(v, float) else v for k, v in asdict(result).items()}
            results[variant].append(row)
            simulations[variant] = simulated
        write_trace(f"{test.folder}_{test.kind}", measured, simulations)
        ct, lin = results["charge_transfer"][-1], results["linear"][-1]
        print(
            f"{test.folder:8s} {test.kind:7s} RMS {ct['rms_mv']:6.1f} mV "
            f"(linear {lin['rms_mv']:6.1f})  max {ct['max_abs_mv']:6.1f}"
        )
    excluded = [
        {"folder": folder, "kind": kind, "reason": reason}
        for (folder, kind), reason in sorted(catalog.EXCLUDED.items())
    ]
    out = {"trace_step_s": TRACE_STEP_S, "excluded": excluded, "variants": results}
    (DATA / "validation.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    write_profiles()
    print(f"{len(results['linear'])} tests in {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()

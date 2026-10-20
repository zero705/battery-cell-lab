"""Identify the cell model from the raw test data and write data/model.json.

For each of the six chamber temperatures: build the open-circuit voltage curve from the HPPC
rests and the C/20 discharge (celllab.ocv), then fit the circuit parameters at every state of
charge of the HPPC test (celllab.identify), with and without the charge-transfer term.

    python tools/fetch_dataset.py       # once: download and verify the raw data
    python tools/identify_model.py      # a few minutes
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from celllab import catalog, identify, ocv  # noqa: E402
from celllab.ecm import PARAMETERS  # noqa: E402
from celllab.measurements import read_mat  # noqa: E402
from celllab.model_file import MODEL_FILE, VARIANTS, Variant  # noqa: E402

DIGITS = 6  # significant digits kept in the file


def sig(value: float) -> float:
    return float(f"{value:.{DIGITS}g}")


def build(
    variants: tuple[Variant, ...] = VARIANTS, slope_correction: bool = True
) -> dict[str, Any]:
    """What data/model.json holds; tools/compare_variants.py also builds it without the slope
    correction of the fit."""
    manifest = json.loads(catalog.MANIFEST.read_text(encoding="utf-8"))
    temperatures = []
    loo: list[float] = []
    for folder, ambient in catalog.AMBIENT_C.items():
        start = time.time()
        hppc = read_mat(catalog.find(folder, "HPPC").path)
        c20 = read_mat(catalog.find(folder, "C20DisCh").path)
        curve, points = ocv.build(hppc, c20)
        loo += ocv.leave_one_out(hppc, c20).tolist()
        fitted = {}
        for variant in variants:
            fits = identify.fit_temperature(
                hppc,
                curve,
                points,
                charge_transfer=variant == "charge_transfer",
                slope_correction=slope_correction,
            )
            fitted[variant] = {
                "levels": [
                    {
                        "charge_ah": sig(f.charge_ah),
                        "temperature_c": sig(f.temperature_c),
                        **{name: sig(f.values[name]) for name in PARAMETERS},
                        "rms_v": sig(f.rms_v),
                        "pulse_rms_v": sig(f.pulse_rms_v),
                        "samples": f.samples,
                        "longest_rest_s": sig(f.longest_rest_s),
                        "identifiable": f.identifiable,
                    }
                    for f in fits
                ]
            }
        level_temps = [lv["temperature_c"] for lv in fitted[variants[0]]["levels"]]
        temperatures.append(
            {
                "folder": folder,
                "ambient_c": ambient,
                "temperature_c": sig(float(np.mean(level_temps))),
                "hppc_file": catalog.find(folder, "HPPC").path.name,
                "c20_file": catalog.find(folder, "C20DisCh").path.name,
                "ocv": {
                    "charge_ah": [round(float(q), 4) for q in curve.charge_ah],
                    "voltage_v": [round(float(v), 5) for v in curve.voltage_v],
                },
                "rest_points": [
                    {
                        "charge_ah": sig(p.charge_ah),
                        "voltage_v": sig(p.voltage_v),
                        "temperature_c": sig(p.temperature_c),
                    }
                    for p in points
                ],
                "variants": fitted,
            }
        )
        print(
            f"{folder}: {len(points)} rest points, {len(fitted[variants[0]]['levels'])} "
            f"states of charge, {time.time() - start:.0f} s"
        )
    loo_mv = np.array(loo) * 1e3
    return {
        "dataset": {k: manifest[k] for k in ("dataset", "doi", "authors", "licence")},
        "ocv_leave_one_out": {
            "points": len(loo),
            "rms_mv": sig(float(np.sqrt(np.mean(loo_mv**2)))),
            "max_abs_mv": sig(float(np.max(np.abs(loo_mv)))),
        },
        "temperatures": temperatures,
    }


def main() -> None:
    model = build()
    MODEL_FILE.write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {MODEL_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

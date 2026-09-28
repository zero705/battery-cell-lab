"""Cut example pulses out of the HPPC tests for the app: data/pulses.csv.

For each chamber temperature, the first discharge pulse and the charge pulse after it, at the
state of charge nearest to half full, with 20 s before and 200 s after. The app runs the model
over the same current to show how each part of the circuit shapes the voltage.

    python tools/extract_examples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from celllab import catalog, identify, ocv  # noqa: E402
from celllab.measurements import read_mat  # noqa: E402

BEFORE_S, AFTER_S = 20.0, 200.0
HALF_AH = 1.4


def main() -> None:
    lines = [
        "# Example HPPC pulses from the McMaster LG 18650HG2 data (CC BY 4.0), cut by",
        "# tools/extract_examples.py: the first pulse pair nearest half full",
        "ambient_c,time_s,current_a,voltage_v,temperature_c,charge_ah",
    ]
    for folder, ambient in catalog.AMBIENT_C.items():
        hppc = read_mat(catalog.find(folder, "HPPC").path)
        c20 = read_mat(catalog.find(folder, "C20DisCh").path)
        _, points = ocv.build(hppc, c20)
        q = hppc.charge_removed_ah
        start, _ = min(identify.windows(hppc, points), key=lambda w: abs(q[w[0]] - HALF_AH))
        first = start + int(np.flatnonzero(hppc.current_a[start:] < -identify.PULSE_A)[0])
        t0 = hppc.time_s[first]
        keep = (hppc.time_s >= t0 - BEFORE_S) & (hppc.time_s <= t0 + 50.0 + AFTER_S)
        for k in np.flatnonzero(keep):
            lines.append(
                f"{ambient:g},{hppc.time_s[k] - t0:.3f},{hppc.current_a[k]:.4f},"
                f"{hppc.voltage_v[k]:.5f},{hppc.temperature_c[k]:.2f},{q[k]:.5f}"
            )
    (ROOT / "data" / "pulses.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {len(lines) - 3} rows")


if __name__ == "__main__":
    main()

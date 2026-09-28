"""Check every raw file of the dataset and print what needs care.

    python tools/audit_dataset.py

Reports the rows that repeat a time stamp, files where time goes backwards or values are
missing, the Wh column, and a summary of every drive-cycle test (duration, charge, voltages,
temperatures), from which the exclusions in celllab/catalog.py follow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import scipy.io

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from celllab import catalog  # noqa: E402
from celllab.measurements import read_mat  # noqa: E402


def main() -> None:
    repeated = same = files_with_repeats = 0
    worst_dv = worst_di = 0.0
    broken = []
    for path in sorted(catalog.RAW.rglob("*.mat")):
        meas = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)["meas"]
        t = np.atleast_1d(np.asarray(meas.Time, dtype=float))
        v = np.atleast_1d(np.asarray(meas.Voltage, dtype=float))
        i = np.atleast_1d(np.asarray(meas.Current, dtype=float))
        if np.isnan(t).any() or np.isnan(v).any() or np.any(np.diff(t) < 0):
            broken.append(path.name)
            continue
        k = np.flatnonzero(np.diff(t) == 0)
        if len(k):
            files_with_repeats += 1
            repeated += len(k)
            same += int(np.sum((v[k + 1] == v[k]) & (i[k + 1] == i[k])))
            worst_dv = max(worst_dv, float(np.max(np.abs(v[k + 1] - v[k]))))
            worst_di = max(worst_di, float(np.max(np.abs(i[k + 1] - i[k]))))
    print(
        f"{repeated} rows in {files_with_repeats} files repeat the previous time stamp; "
        f"{same} repeat the values too; the others differ by at most "
        f"{worst_dv * 1e3:.1f} mV and {worst_di * 1e3:.0f} mA"
    )
    print("files with time going backwards or missing values:", broken or "none")
    udds = read_mat(catalog.find("25degC", "UDDS").path)
    meas = scipy.io.loadmat(
        catalog.find("25degC", "UDDS").path, squeeze_me=True, struct_as_record=False
    )["meas"]
    energy = np.trapezoid(udds.voltage_v * udds.current_a, udds.time_s) / 3600
    print(
        f"Wh column of the 25 degC UDDS test: {sorted(set(np.atleast_1d(meas.Wh).tolist()))}; "
        f"energy moved {abs(energy):.1f} Wh"
    )
    print("\ndrive cycles: folder, test, hours, Ah removed, V start -> end, cell temperature")
    for test in catalog.dataset_files():
        if test.kind not in catalog.DRIVE_CYCLES:
            continue
        try:
            m = read_mat(test.path)
        except ValueError as error:
            print(f"  {test.folder:8s} {test.kind:7s} unreadable: {error}")
            continue
        q = m.charge_removed_ah[-1]
        note = catalog.EXCLUDED.get((test.folder, test.kind), "")
        print(
            f"  {test.folder:8s} {test.kind:7s} {m.time_s[-1] / 3600:5.2f} h {q:6.3f} Ah "
            f"{m.voltage_v[0]:.3f} -> {m.voltage_v[-1]:.3f} V "
            f"{m.temperature_c[0]:6.1f} .. {m.temperature_c.max():6.1f} degC  {note}"
        )


if __name__ == "__main__":
    main()

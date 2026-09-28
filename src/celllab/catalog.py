"""Which file of the dataset holds which test, and which tests are left out and why."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
MANIFEST = DATA / "dataset.json"
RAW = DATA / "raw"

# Folder name -> the chamber (ambient) temperature of the tests in it, degC.
AMBIENT_C = {
    "n20degC": -20.0,
    "n10degC": -10.0,
    "0degC": 0.0,
    "10degC": 10.0,
    "25degC": 25.0,
    "40degC": 40.0,
}
DRIVE_CYCLES = ("UDDS", "HWFET", "LA92", "US06", *(f"Mixed{n}" for n in range(1, 9)))
_KIND = re.compile(r" \d+_(HPPC|C20DisCh|UDDS|HWFET|LA92|US06|Mixed\d)_")

# Tests that are in the dataset but cannot be used, found by tools/audit_dataset.py.
EXCLUDED = {
    ("25degC", "HWFET"): "no current flows: the file is 10 minutes of rest",
    ("10degC", "LA92"): "time goes backwards in four places and three rows are missing",
    **{
        ("40degC", f"Mixed{n}"): "run at about 23 degC, not 40 degC, and stopped after 0.19 Ah"
        for n in range(4, 9)
    },
}


@dataclass(frozen=True)
class DatasetFile:
    folder: str
    kind: str
    path: Path

    @property
    def ambient_c(self) -> float:
        return AMBIENT_C[self.folder]


def _manifest() -> list[dict[str, str]]:
    files: list[dict[str, str]] = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    return files


def dataset_files() -> list[DatasetFile]:
    """Every HPPC, C/20 and drive-cycle file listed in the manifest, excluded ones included."""
    found = []
    for entry in _manifest():
        match = _KIND.search(entry["filename"])
        if match:
            path = RAW / entry["folder"] / entry["filename"]
            found.append(DatasetFile(entry["folder"], match.group(1), path))
    return found


def find(folder: str, kind: str) -> DatasetFile:
    """The one file of a test at one temperature."""
    matches = [f for f in dataset_files() if f.folder == folder and f.kind == kind]
    if len(matches) != 1:
        raise LookupError(f"{len(matches)} files for {kind} at {folder}")
    return matches[0]


def drive_cycles() -> list[DatasetFile]:
    """The drive-cycle tests used for validation: all of them except the excluded ones."""
    return sorted(
        (
            f
            for f in dataset_files()
            if f.kind in DRIVE_CYCLES and (f.folder, f.kind) not in EXCLUDED
        ),
        key=lambda f: (f.ambient_c, DRIVE_CYCLES.index(f.kind)),
    )

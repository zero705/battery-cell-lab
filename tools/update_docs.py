"""Rewrite the generated tables of README.md and docs/method.md from data/.

A table sits between <!-- generated: name --> and <!-- end generated -->. tests/test_docs.py
fails if a document no longer matches what this script writes.

    python tools/update_docs.py           # rewrite the tables
    python tools/update_docs.py --check   # only check
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCUMENTS = ("README.md", "docs/method.md")
TEMPERATURES = (-20.0, -10.0, 0.0, 10.0, 25.0, 40.0)
BLOCK = re.compile(
    r"(<!-- generated: (?P<name>[a-z_]+) -->\n)(?P<body>.*?)(<!-- end generated -->)", re.DOTALL
)


def _validation() -> dict[str, list[dict[str, object]]]:
    data: dict[str, list[dict[str, object]]] = json.loads(
        (DATA / "validation.json").read_text(encoding="utf-8")
    )["variants"]
    return data


def _rms(rows: list[dict[str, object]], **match: object) -> list[float]:
    return [
        float(r["rms_mv"])  # type: ignore[arg-type]
        for r in rows
        if all(r[k] == v for k, v in match.items())
    ]


def results() -> str:
    """Median RMS error per temperature, development and test sets, both variants."""
    data = _validation()
    lines = [
        "| Chamber temperature | Tests | Median error, development set | Median error, test set "
        "| Median error, all tests | Worst test | Median error, two RC pairs only |",
        "|---|---|---|---|---|---|---|",
    ]
    ct, lin = data["charge_transfer"], data["linear"]
    for t_c in TEMPERATURES:
        dev = _rms(ct, ambient_c=t_c, split="development")
        test = _rms(ct, ambient_c=t_c, split="test")
        both = dev + test
        lines.append(
            f"| {t_c:g} °C | {len(both)} | {statistics.median(dev):.1f} mV "
            f"| {statistics.median(test):.1f} mV | {statistics.median(both):.1f} mV "
            f"| {max(both):.1f} mV | {statistics.median(_rms(lin, ambient_c=t_c)):.1f} mV |"
        )
    dev, test = _rms(ct, split="development"), _rms(ct, split="test")
    lines.append(
        f"| **All** | **{len(dev) + len(test)}** | **{statistics.median(dev):.1f} mV** "
        f"| **{statistics.median(test):.1f} mV** | **{statistics.median(dev + test):.1f} mV** "
        f"| **{max(dev + test):.1f} mV** | **{statistics.median(_rms(lin)):.1f} mV** |"
    )
    return "\n".join(lines)


def every_test() -> str:
    """Every test of the validation, with both variants."""
    data = _validation()
    lines = [
        "| °C | Test | Set | Hours | Ah removed | RMS error | 95th percentile | Largest "
        "| RMS, two RC pairs only |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    linear = {(r["folder"], r["kind"]): r for r in data["linear"]}
    for r in data["charge_transfer"]:
        lin = linear[(r["folder"], r["kind"])]
        lines.append(
            f"| {r['ambient_c']:g} | {r['kind']} | {r['split']} | {r['duration_h']:.2f} "
            f"| {r['charge_removed_ah']:.2f} | {r['rms_mv']:.1f} mV | {r['p95_abs_mv']:.0f} mV "
            f"| {r['max_abs_mv']:.0f} mV | {lin['rms_mv']:.1f} mV |"
        )
    return "\n".join(lines)


def parameters() -> str:
    """The identified parameters at the state of charge nearest half full, per temperature."""
    model = json.loads((DATA / "model.json").read_text(encoding="utf-8"))
    lines = [
        "| Chamber | Cell | R0 | R1 | tau1 | R2 | tau2 | i0 | Fit error (window RMS) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in model["temperatures"]:
        levels = [lv for lv in entry["variants"]["charge_transfer"]["levels"] if lv["identifiable"]]
        lv = min(levels, key=lambda x: abs(x["charge_ah"] - 1.5))
        lines.append(
            f"| {entry['ambient_c']:g} °C | {lv['temperature_c']:.1f} °C "
            f"| {lv['r0_ohm'] * 1e3:.1f} mΩ | {lv['r1_ohm'] * 1e3:.1f} mΩ | {lv['tau1_s']:.1f} s "
            f"| {lv['r2_ohm'] * 1e3:.0f} mΩ | {lv['tau2_s']:.0f} s | {lv['i0_a']:.3g} A "
            f"| {lv['rms_v'] * 1e3:.1f} mV |"
        )
    return "\n".join(lines)


DEVELOPMENT_ROWS = {
    "first": "First: no slope correction, every level",
    "slope_correction": "Slope correction only",
    "identifiability_rule": "Identifiability rule only",
    "both": "Both (the model)",
}


def development() -> str:
    """The comparisons on the development set, from tools/compare_variants.py."""
    data = json.loads((DATA / "development.json").read_text(encoding="utf-8"))
    lines = [
        "| Model | Levels used | Median error | RMS of the per-test errors |",
        "|---|---|---|---|",
    ]
    for name, label in DEVELOPMENT_ROWS.items():
        variant = data["variants"][name]
        lines.append(
            f"| {label} | {variant['levels']} | {variant['development']['median_mv']:.1f} mV "
            f"| {variant['development']['rms_of_rms_mv']:.1f} mV |"
        )
    return "\n".join(lines)


BLOCKS: dict[str, Callable[[], str]] = {
    "results": results,
    "every_test": every_test,
    "parameters": parameters,
    "development": development,
}


def refresh(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in BLOCKS:
            raise KeyError(f"unknown generated block {name!r}")
        return f"{match.group(1)}{BLOCKS[name]()}\n{match.group(4)}"

    return BLOCK.sub(replace, text)


def main(argv: list[str]) -> int:
    stale = []
    for name in DOCUMENTS:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        new = refresh(text)
        if new != text:
            stale.append(name)
            if "--check" not in argv:
                path.write_text(new, encoding="utf-8", newline="\n")
    for name in stale:
        print(("stale  " if "--check" in argv else "wrote  ") + name)
    return 1 if stale and "--check" in argv else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

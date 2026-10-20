"""Draw the README figures into docs/images from data/ (no raw data needed).

python tools/make_figures.py
"""

from __future__ import annotations

import gzip
import io
import json
import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from celllab import lab, load_model  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "docs" / "images"
TEMPERATURES = (-20.0, -10.0, 0.0, 10.0, 25.0, 40.0)
INK, MUTED, GRID = "#1d232a", "#5b6570", "#e3e7eb"
MEASURED, MODEL = "#1d232a", "#d96a2b"

mpl.rcParams.update(
    {
        "font.size": 10,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.grid": True,
        "grid.color": GRID,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 150,
        "svg.hashsalt": "battery-cell-lab",
    }
)


def trace(folder: str, kind: str) -> dict[str, np.ndarray]:
    raw = gzip.decompress((DATA / "traces" / f"{folder}_{kind}.csv.gz").read_bytes())
    table = np.genfromtxt(io.BytesIO(raw), delimiter=",", names=True)
    return {name: np.asarray(table[name]) for name in table.dtype.names or ()}


def save(fig: Figure, name: str) -> None:
    fig.savefig(OUT / name, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)


def validation_example() -> None:
    fig, axes = plt.subplots(
        2, 2, figsize=(11, 5.6), sharex="col", gridspec_kw={"height_ratios": [3, 1]}
    )
    for col, (folder, kind, label) in enumerate(
        [("25degC", "LA92", "LA92 at 25 °C"), ("n20degC", "UDDS", "UDDS at -20 °C")]
    ):
        t = trace(folder, kind)
        hours = t["time_s"] / 3600
        axes[0, col].plot(hours, t["measured_v"], color=MEASURED, lw=0.6, label="Measured")
        axes[0, col].plot(
            hours, t["charge_transfer_v"], color=MODEL, lw=0.6, alpha=0.85, label="Model"
        )
        axes[0, col].set_title(label, loc="left", color=INK)
        axes[0, col].set_ylabel("Voltage (V)")
        error = 1e3 * (t["charge_transfer_v"] - t["measured_v"])
        axes[1, col].plot(hours, error, color=MODEL, lw=0.5)
        axes[1, col].axhline(0, color=MUTED, lw=0.8)
        axes[1, col].set_ylabel("Error (mV)")
        axes[1, col].set_xlabel("Time (h)")
    axes[0, 0].legend(frameon=False, loc="lower left")
    fig.tight_layout()
    save(fig, "validation.png")


def error_by_temperature() -> None:
    data = json.loads((DATA / "validation.json").read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for offset, variant, colour, label in [
        (-0.12, "linear", "#9aa5b1", "Two RC pairs only"),
        (0.12, "charge_transfer", MODEL, "With the Butler-Volmer term (this model)"),
    ]:
        rows = data["variants"][variant]
        for k, t_c in enumerate(TEMPERATURES):
            values = [r["rms_mv"] for r in rows if r["ambient_c"] == t_c]
            x = np.full(len(values), k + offset)
            ax.scatter(x, values, s=14, color=colour, alpha=0.8, label=label if k == 0 else None)
            ax.plot(
                [k + offset - 0.08, k + offset + 0.08], [np.median(values)] * 2, color=colour, lw=2
            )
    ax.set_xticks(range(len(TEMPERATURES)), [f"{t:g} °C" for t in TEMPERATURES])
    ax.set_ylabel("RMS error per test (mV)")
    ax.set_ylim(0, None)
    ax.legend(frameon=False, loc="upper right")
    tests = len(data["variants"]["charge_transfer"])
    ax.set_title(
        f"Error on the {tests} drive-cycle tests; bars mark the median", loc="left", color=INK
    )
    fig.tight_layout()
    save(fig, "error_by_temperature.png")


def cold_weather() -> None:
    model = load_model()
    profiles = lab.load_profiles()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    width = 0.2
    for j, cycle in enumerate(("UDDS", "HWFET", "LA92", "US06")):
        energies = [lab.drive(model, profiles[cycle], cycle, t).energy_wh for t in TEMPERATURES]
        ax.bar(
            np.arange(len(TEMPERATURES)) + (j - 1.5) * width,
            energies,
            width,
            label=cycle,
            color=["#1f4e9c", "#6ca8e8", "#e3a33b", "#a8321d"][j],
        )
    ax.set_xticks(range(len(TEMPERATURES)), [f"{t:g} °C" for t in TEMPERATURES])
    ax.set_ylabel("Energy delivered (Wh)")
    ax.legend(frameon=False, ncols=4, loc="upper left")
    ax.set_title("Energy one full cell gives on each drive cycle (model)", loc="left", color=INK)
    fig.tight_layout()
    save(fig, "cold_weather.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    validation_example()
    error_by_temperature()
    cold_weather()
    print("figures written to docs/images")


if __name__ == "__main__":
    main()

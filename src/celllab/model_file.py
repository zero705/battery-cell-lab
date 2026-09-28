"""The identified model, stored in data/model.json so that it can be used without the raw data.

tools/identify_model.py writes the file from the raw test data; load_model() reads it. The file
holds, for each chamber temperature: the open-circuit voltage curve, the rest points it passes
through, and the parameters at every state of charge for two variants of the circuit, with and
without the Butler-Volmer charge-transfer term.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np

from celllab.ecm import PARAMETERS, CellModel, TemperatureTable
from celllab.ocv import OcvCurve

MODEL_FILE = Path(__file__).resolve().parents[2] / "data" / "model.json"
Variant = Literal["charge_transfer", "linear"]
VARIANTS: tuple[Variant, ...] = ("charge_transfer", "linear")


def read(path: Path = MODEL_FILE) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def load_model(variant: Variant = "charge_transfer", path: Path = MODEL_FILE) -> CellModel:
    """The cell model of one variant, from data/model.json, from its identifiable levels."""
    data = read(path)
    tables = []
    for entry in data["temperatures"]:
        levels = [lv for lv in entry["variants"][variant]["levels"] if lv["identifiable"]]
        tables.append(
            TemperatureTable(
                ambient_c=float(entry["ambient_c"]),
                temperature_c=float(entry["temperature_c"]),
                ocv=OcvCurve(
                    np.asarray(entry["ocv"]["charge_ah"], dtype=float),
                    np.asarray(entry["ocv"]["voltage_v"], dtype=float),
                ),
                charge_ah=np.array([lv["charge_ah"] for lv in levels], dtype=float),
                values={
                    name: np.array([lv[name] for lv in levels], dtype=float) for name in PARAMETERS
                },
            )
        )
    return CellModel(tuple(sorted(tables, key=lambda t: t.temperature_c)))

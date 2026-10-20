"""The virtual lab: drive the model with a car's power demand, the way the tests drove the cell.

The dataset's drive-cycle tests use a power profile "calculated for a single LG HG2 cell in a
compact electric vehicle" (the dataset's readme), repeated until the cell has given 95 % of its
1C capacity. data/profiles.csv has one period of each of the four standard cycles, as the
40 degC tests applied it.

The tests limited the current. Discharge was held to 6 A at -20 degC and 12 A at -10 degC (from
0 degC up the cell followed the demand, up to 18 A). The charging current of regenerative
braking was held to 1.5 A at -20 degC, 3 A at -10 and 0 degC and 6 A from 10 degC. In the
drive-cycle data the current sits at these values for long stretches and goes past them by at
most 0.3 A, only for a moment. The cycler also never let the voltage fall below 2.8 V, the
lowest the tests discharge to; there it gave what the cell could give at 2.8 V. The lab does
the same, with the limits of the closest tested temperature at or below the one chosen. In the
-20 degC US06 test these limits cut the discharge energy of the first period to 82 % of what
the cycle asks for.

The drive ends with the first period in which the cell gives less than MIN_SHARE of the
discharge energy the cycle asks for. From then on the car can't keep up with the cycle. This
threshold is my definition for the lab, not a property of the cell.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from celllab.ecm import CellModel, Limits, Simulation, simulate_power
from celllab.measurements import Array

PROFILES = Path(__file__).resolve().parents[2] / "data" / "profiles.csv"
CUTOFF_V = 2.8
# (tested temperature degC, current limit A), from the coldest up
DISCHARGE_LIMIT_A = ((-20.0, 6.0), (-10.0, 12.0), (0.0, math.inf))
REGEN_LIMIT_A = ((-20.0, 1.5), (-10.0, 3.0), (0.0, 3.0), (10.0, 6.0))
MAX_REPEATS = 40
MIN_SHARE = 0.9


def _at_or_below(table: tuple[tuple[float, float], ...], temperature_c: float) -> float:
    """The limit of the nearest tested temperature at or below; the coldest one below it."""
    limit = table[0][1]
    for tested_c, amps in table:
        if temperature_c >= tested_c:
            limit = amps
    return limit


def discharge_limit_a(temperature_c: float) -> float:
    """The tests' limit on the discharge current (infinite where they had none)."""
    return _at_or_below(DISCHARGE_LIMIT_A, temperature_c)


def regen_limit_a(temperature_c: float) -> float:
    """The tests' limit on the charging current of regenerative braking."""
    return _at_or_below(REGEN_LIMIT_A, temperature_c)


def limits(temperature_c: float) -> Limits:
    """What the cycler allowed at a temperature: the current limits and the hold at 2.8 V."""
    return Limits(
        min_voltage_v=CUTOFF_V,
        max_charge_a=regen_limit_a(temperature_c),
        max_discharge_a=discharge_limit_a(temperature_c),
        voltage_floor=True,
    )


def load_profiles(path: Path = PROFILES) -> dict[str, Array]:
    """Power demand of one period of each cycle, W at 1 s steps, negative on discharge."""
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(line for line in f if not line.startswith("#")))
    header, data = rows[0], rows[1:]
    profiles = {}
    for column, name in enumerate(header[1:], start=1):
        values = [float(row[column]) for row in data if row[column] != ""]
        profiles[name] = np.array(values)
    return profiles


@dataclass(frozen=True)
class Drive:
    cycle: str
    temperature_c: float
    simulation: Simulation
    period_s: int
    demand_w: Array  # the demand over the steps of the simulation

    @property
    def share_delivered(self) -> float:
        """Discharge energy delivered as a share of the discharge energy demanded."""
        delivered = self.simulation.voltage_v * self.simulation.current_a
        demanded = np.minimum(self.demand_w, 0.0).sum()
        return float(np.minimum(delivered, 0.0).sum() / demanded) if demanded else 1.0

    @property
    def energy_wh(self) -> float:
        """Net energy out of the cell (discharge minus regenerative braking), Wh."""
        s = self.simulation
        return float(-np.sum(s.voltage_v * s.current_a) / 3600)  # 1 s steps

    @property
    def charge_ah(self) -> float:
        """Net charge out of the cell, Ah: each step holds its current for 1 s."""
        return float(-np.sum(self.simulation.current_a) / 3600)

    @property
    def heat_wh(self) -> float:
        return float(np.sum(self.simulation.heat_w) / 3600)

    @property
    def duration_h(self) -> float:
        return len(self.simulation.time_s) / 3600

    @property
    def cycles_completed(self) -> float:
        return len(self.simulation.time_s) / self.period_s


def drive(
    model: CellModel,
    profile_w: Array,
    cycle: str,
    temperature_c: float,
    initial_charge_ah: float = 0.0,
) -> Drive:
    """Repeat one cycle's power demand from initial_charge_ah until the cell cannot follow it."""
    period = len(profile_w)
    demand = np.tile(profile_w, MAX_REPEATS)
    simulation = simulate_power(
        model,
        demand,
        1.0,
        temperature_c,
        initial_charge_ah=initial_charge_ah,
        limits=limits(temperature_c),
    )
    delivered = np.minimum(simulation.voltage_v * simulation.current_a, 0.0)
    demanded = np.minimum(demand[: len(delivered)], 0.0)
    end = len(delivered)
    for start in range(0, len(delivered), period):
        stop = min(start + period, len(delivered))
        if delivered[start:stop].sum() > MIN_SHARE * demanded[start : start + period].sum():
            end = stop  # less than MIN_SHARE delivered (the sums are negative)
            break
    return Drive(cycle, temperature_c, _head(simulation, end), period, demand[:end])


def _head(s: Simulation, n: int) -> Simulation:
    return Simulation(
        s.time_s[:n],
        s.current_a[:n],
        s.temperature_c[:n],
        s.charge_ah[:n],
        s.ocv_v[:n],
        s.ohmic_v[:n],
        s.charge_transfer_v[:n],
        s.rc1_v[:n],
        s.rc2_v[:n],
    )

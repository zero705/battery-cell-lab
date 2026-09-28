"""The virtual lab: drive the model with a vehicle's power demand, as the tests drove the cell.

The dataset's drive-cycle tests apply a power profile "calculated for a single LG HG2 cell in a
compact electric vehicle" (the dataset's readme), repeated until the cell has given 95 % of its
1C capacity. data/profiles.csv holds one period of each of the four standard cycles, taken from
the 40 degC tests.

Here a cycle is repeated as the cycler did it: a demand the cell cannot meet without falling
below 2.8 V, the lowest the tests discharge to, is cut to what the cell gives at 2.8 V (in the
-20 degC US06 test the cell delivered 82 % of the discharge power demanded in the first period).
The drive ends with the first period in which the cell gives less than MIN_SHARE of the
discharge energy the cycle demands: from then on the car can no longer keep up with the cycle.
This threshold is a definition of this lab, not a property of the cell.

In the cold the tests limited the charging current of regenerative braking; the largest charge
currents in the drive-cycle data are 1.5 A at -20 degC, 3 A at -10 and 0 degC and 6 A from
10 degC. The lab applies the limit of the nearest tested temperature at or below the one chosen.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from celllab.ecm import CellModel, Simulation, simulate_power
from celllab.measurements import Array

PROFILES = Path(__file__).resolve().parents[2] / "data" / "profiles.csv"
CUTOFF_V = 2.8
REGEN_LIMIT_A = ((-20.0, 1.5), (-10.0, 3.0), (0.0, 3.0), (10.0, 6.0))
MAX_REPEATS = 40
MIN_SHARE = 0.9


def regen_limit_a(temperature_c: float) -> float:
    """The charging-current limit of the tests at the nearest tested temperature at or below."""
    limit = REGEN_LIMIT_A[0][1]
    for tested_c, amps in REGEN_LIMIT_A:
        if temperature_c >= tested_c:
            limit = amps
    return limit


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
        min_voltage_v=CUTOFF_V,
        max_charge_a=regen_limit_a(temperature_c),
        voltage_floor=True,
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

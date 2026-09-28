"""The virtual lab."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import TRUE, constant_table, linear_ocv

from celllab import lab
from celllab.ecm import CellModel, simulate_power


def test_profiles_hold_one_period_of_each_cycle() -> None:
    profiles = lab.load_profiles()
    assert {k: len(v) for k, v in profiles.items()} == {
        "UDDS": 1370,
        "HWFET": 766,
        "LA92": 1438,
        "US06": 601,
    }
    for power in profiles.values():
        assert power.min() < -15.0  # discharge peaks
        assert power.max() > 15.0  # regenerative braking
        assert np.mean(power) < 0  # a drive takes energy out on balance


@pytest.mark.parametrize(
    ("temperature_c", "limit"),
    [(-30.0, 1.5), (-20.0, 1.5), (-15.0, 1.5), (-10.0, 3.0), (5.0, 3.0), (10.0, 6.0), (40.0, 6.0)],
)
def test_regen_limit_follows_the_tests(temperature_c: float, limit: float) -> None:
    assert lab.regen_limit_a(temperature_c) == limit


def test_colder_drives_deliver_less_energy(model: CellModel) -> None:
    profile = lab.load_profiles()["UDDS"]
    energies = [lab.drive(model, profile, "UDDS", t).energy_wh for t in (-20.0, 0.0, 25.0)]
    assert energies[0] < energies[1] < energies[2]


def test_drive_ends_when_the_cell_falls_behind_the_demand(model: CellModel) -> None:
    profile = lab.load_profiles()["US06"]
    cold = lab.drive(model, profile, "US06", -20.0)
    assert cold.cycles_completed == pytest.approx(1.0)  # it cannot keep up from the start
    assert cold.share_delivered < lab.MIN_SHARE
    warm = lab.drive(model, profile, "US06", 25.0)
    assert warm.cycles_completed > 5
    assert warm.simulation.voltage_v.min() >= lab.CUTOFF_V - 1e-9


@pytest.mark.parametrize(
    ("cycle", "temperature_c", "start_ah"),
    [("US06", 0.0, 0.65 * 2.775), ("US06", -20.0, 0.0), ("LA92", -10.0, 1.5), ("HWFET", 40.0, 2.2)],
)
def test_the_cell_never_discharges_below_the_cut_off(
    model: CellModel, cycle: str, temperature_c: float, start_ah: float
) -> None:
    """While charging, a cell polarised by a hard discharge may sit just below 2.8 V (the
    first case does, by 0.8 mV); while discharging it never does."""
    d = lab.drive(model, lab.load_profiles()[cycle], cycle, temperature_c, start_ah)
    s = d.simulation
    discharging = s.current_a < 0
    assert s.voltage_v[discharging].min() >= lab.CUTOFF_V - 1e-9
    assert s.voltage_v.max() <= 4.2 + 1e-9


def test_energy_and_charge_add_up(model: CellModel) -> None:
    d = lab.drive(model, lab.load_profiles()["HWFET"], "HWFET", 25.0)
    s = d.simulation
    assert d.energy_wh == pytest.approx(-np.sum(s.voltage_v * s.current_a) / 3600)
    assert d.charge_ah == pytest.approx(s.charge_ah[-1] - s.charge_ah[0] - s.current_a[-1] / 3600)
    assert d.heat_wh > 0
    assert d.duration_h == pytest.approx(len(s.time_s) / 3600)
    assert 0 < d.share_delivered <= 1.0 + 1e-9


def test_voltage_floor_cuts_the_power_instead_of_stopping() -> None:
    ocv = linear_ocv()
    model = CellModel(
        (
            constant_table(0.0, dict(TRUE, r0_ohm=0.3), ocv),
            constant_table(40.0, dict(TRUE, r0_ohm=0.3), ocv),
        )
    )
    demand = np.full(50, -12.0)  # beyond what 4 V and 0.3 ohm can give above 3.5 V
    stopped = simulate_power(model, demand, 1.0, 25.0, min_voltage_v=3.5)
    held = simulate_power(model, demand, 1.0, 25.0, min_voltage_v=3.5, voltage_floor=True)
    assert len(stopped.time_s) == 0
    assert len(held.time_s) == 50
    assert held.voltage_v == pytest.approx(np.full(50, 3.5), abs=1e-9)
    empty = simulate_power(
        model, demand, 1.0, 25.0, initial_charge_ah=2.0, min_voltage_v=3.5, voltage_floor=True
    )
    assert len(empty.time_s) == 0  # at 2 Ah the open-circuit voltage is 3.4 V: nothing to give

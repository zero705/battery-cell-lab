"""The circuit model behaves as its equations say."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import TRUE, constant_table, linear_ocv

from celllab.ecm import (
    FARADAY,
    GAS_CONSTANT,
    KELVIN,
    PARAMETERS,
    CellModel,
    TemperatureTable,
    charge_transfer_v,
    rc_response,
    simulate_current,
    simulate_power,
)


def test_physical_constants_are_the_exact_si_values() -> None:
    avogadro, elementary_charge, boltzmann = 6.02214076e23, 1.602176634e-19, 1.380649e-23
    assert pytest.approx(avogadro * elementary_charge, rel=1e-10) == FARADAY
    assert pytest.approx(avogadro * boltzmann, rel=1e-10) == GAS_CONSTANT


def test_rc_step_response_is_exact_for_any_step_length() -> None:
    rng = np.random.default_rng(1)
    t = np.concatenate(([0.0], np.cumsum(rng.uniform(0.05, 20.0, 400))))
    current = np.full_like(t, -2.0)
    u = rc_response(np.diff(t), current, np.full_like(t, 0.01), np.full_like(t, 30.0))
    assert u == pytest.approx(-2.0 * 0.01 * (1 - np.exp(-t / 30.0)), abs=1e-12)


def test_rc_response_relaxes_after_the_current_stops() -> None:
    t = np.arange(0.0, 200.0, 0.5)
    current = np.where(t < 50.0, -3.0, 0.0)
    u = rc_response(np.diff(t), current, np.full_like(t, 0.02), np.full_like(t, 10.0))
    k = np.searchsorted(t, 50.0)
    after = u[k] * np.exp(-(t[k:] - t[k]) / 10.0)
    assert u[k:] == pytest.approx(after, abs=1e-12)


def test_rc_response_checks_lengths() -> None:
    with pytest.raises(ValueError, match="one element less"):
        rc_response(np.ones(3), np.ones(3), np.ones(3), np.ones(3))


def test_charge_transfer_is_ohmic_at_small_current_and_odd() -> None:
    i0, t_c = 2.0, 25.0
    small = 1e-4
    r_ct = GAS_CONSTANT * (t_c + KELVIN) / (FARADAY * i0)
    eta = charge_transfer_v(np.array([small]), np.array([t_c]), np.array([i0]))
    assert eta[0] / small == pytest.approx(r_ct, rel=1e-6)
    both = charge_transfer_v(np.array([5.0, -5.0]), np.full(2, t_c), np.full(2, i0))
    assert both[0] == pytest.approx(-both[1])


def _model(r0_cold: float = 0.08, r0_warm: float = 0.02) -> CellModel:
    ocv = linear_ocv()
    cold = constant_table(-20.0, dict(TRUE, r0_ohm=r0_cold), ocv)
    warm = constant_table(40.0, dict(TRUE, r0_ohm=r0_warm), ocv)
    return CellModel((cold, warm))


def test_parameters_interpolate_arrhenius_in_temperature() -> None:
    model = _model()
    t_mid_c = 1 / ((1 / (-20.0 + KELVIN) + 1 / (40.0 + KELVIN)) / 2) - KELVIN
    r0 = model.parameters(1.0, t_mid_c)["r0_ohm"][0]
    assert r0 == pytest.approx(math.sqrt(0.08 * 0.02), rel=1e-9)  # geometric mean at mid 1/T
    assert model.parameters(1.0, -40.0)["r0_ohm"][0] == pytest.approx(0.08)  # held at the ends
    assert model.parameters(1.0, 60.0)["r0_ohm"][0] == pytest.approx(0.02)


def test_parameters_interpolate_linearly_in_charge() -> None:
    ocv = linear_ocv()
    table = TemperatureTable(
        25.0,
        25.0,
        ocv,
        np.array([0.0, 2.0]),
        {name: np.array([TRUE[name], 3 * TRUE[name]]) for name in PARAMETERS},
    )
    model = CellModel((table, constant_table(40.0, TRUE, ocv)))
    assert model.parameters(1.0, 25.0)["r0_ohm"][0] == pytest.approx(2 * TRUE["r0_ohm"])
    assert model.parameters(5.0, 25.0)["r0_ohm"][0] == pytest.approx(3 * TRUE["r0_ohm"])


def test_ocv_interpolates_linearly_in_temperature() -> None:
    cold = constant_table(0.0, TRUE, linear_ocv(top_v=4.1))
    warm = constant_table(20.0, TRUE, linear_ocv(top_v=4.2))
    model = CellModel((cold, warm))
    assert model.ocv_v(0.0, 10.0)[0] == pytest.approx(4.15)
    assert model.ocv_v(0.0, 50.0)[0] == pytest.approx(4.2)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"values": {"r0_ohm": np.ones(3)}}, "expected parameters"),
        ({"values": {n: np.ones(2) for n in PARAMETERS}}, "values for 3 states"),
        ({"values": {n: -np.ones(3) for n in PARAMETERS}}, "must be positive"),
        ({"charge_ah": np.array([0.0, 2.0, 1.0])}, "must increase"),
    ],
)
def test_table_is_checked(kwargs: dict[str, object], match: str) -> None:
    base: dict[str, object] = {
        "ambient_c": 25.0,
        "temperature_c": 25.0,
        "ocv": linear_ocv(),
        "charge_ah": np.array([0.0, 1.0, 2.0]),
        "values": {n: np.ones(3) for n in PARAMETERS},
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        TemperatureTable(**base)  # type: ignore[arg-type]


def test_model_needs_increasing_temperatures() -> None:
    table = constant_table(25.0, TRUE, linear_ocv())
    with pytest.raises(ValueError, match="two or more"):
        CellModel((table,))
    with pytest.raises(ValueError, match="two or more"):
        CellModel((table, table))


def test_at_rest_the_voltage_is_the_open_circuit_voltage() -> None:
    model = _model()
    t = np.arange(0.0, 100.0, 1.0)
    sim = simulate_current(model, t, np.zeros_like(t), 25.0, initial_charge_ah=1.2)
    assert sim.voltage_v == pytest.approx(np.full_like(t, 4.2 - 0.4 * 1.2))
    assert sim.heat_w == pytest.approx(np.zeros_like(t))


def test_discharge_removes_charge_and_releases_heat() -> None:
    model = _model()
    t = np.arange(0.0, 3600.0, 1.0)
    sim = simulate_current(model, t, np.full_like(t, -3.0), 25.0)
    assert sim.charge_ah[-1] == pytest.approx(3.0 * 3599 / 3600)
    assert np.all(sim.heat_w[1:] > 0)
    assert np.all(sim.voltage_v < sim.ocv_v)


def test_power_mode_delivers_the_demanded_power() -> None:
    model = _model()
    demand = np.full(600, -8.0)
    sim = simulate_power(model, demand, 1.0, 25.0, initial_charge_ah=0.5)
    assert len(sim.time_s) == 600
    assert sim.voltage_v * sim.current_a == pytest.approx(demand, rel=1e-6)


def test_power_mode_stops_at_the_cut_off_voltage() -> None:
    model = _model()
    sim = simulate_power(model, np.full(20000, -10.0), 1.0, 25.0, min_voltage_v=3.5)
    assert len(sim.time_s) < 20000
    assert sim.voltage_v.min() >= 3.5


def test_power_mode_stops_when_the_power_is_out_of_reach() -> None:
    model = _model(r0_cold=0.5, r0_warm=0.5)
    # 4 V and 0.5 ohm deliver at most (4^2)/(4*0.5) = 8 W; 50 W is impossible.
    sim = simulate_power(model, np.full(10, -50.0), 1.0, 25.0, min_voltage_v=0.0)
    assert len(sim.time_s) == 0


def test_power_mode_caps_charging_current_and_voltage() -> None:
    model = _model()
    sim = simulate_power(
        model, np.full(100, 20.0), 1.0, 25.0, initial_charge_ah=1.5, max_charge_a=1.5
    )
    assert sim.current_a.max() == pytest.approx(1.5)
    full = simulate_power(model, np.full(100, 20.0), 1.0, 25.0, initial_charge_ah=0.0)
    assert full.voltage_v.max() <= 4.2 + 1e-9
    assert simulate_power(model, np.zeros(5), 1.0, 25.0).current_a == pytest.approx(np.zeros(5))

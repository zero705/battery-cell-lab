"""The equivalent circuit model: two RC pairs and a Butler-Volmer charge-transfer term.

Terminal voltage, with the current i positive on charge:

    v = OCV(q, T) + R0 i + eta(i) + u1 + u2
    eta(i) = (2 R_gas T / F) asinh(i / (2 i0))          charge transfer, symmetric, alpha = 1/2
    du_k/dt = (R_k i - u_k) / tau_k,  k = 1, 2           the two RC pairs

q is the charge removed since the cell was full. The RC pairs are advanced exactly over each
sample interval with the current held at the value at its start (zero-order hold), which is
exact for any step length:  u[n+1] = a u[n] + R (1 - a) i[n],  a = exp(-dt / tau).

The parameters R0, R1, tau1, R2, tau2 and i0 are identified at each temperature and state of
charge of the HPPC test (identify.py). Between states of charge they are interpolated linearly
in q; between temperatures their logarithm is interpolated linearly in 1/T, the Arrhenius form
that thermally activated processes follow. The open-circuit voltage is interpolated linearly in
temperature. Outside the tested range, values are held at the nearest end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from celllab.measurements import Array
from celllab.ocv import OcvCurve

Index = npt.NDArray[np.signedinteger[Any]]

# Exact in the SI since 2019 (CODATA 2018), rounded to ten significant digits.
FARADAY = 96485.33212  # C/mol
GAS_CONSTANT = 8.314462618  # J/(mol K)
KELVIN = 273.15
PARAMETERS = ("r0_ohm", "r1_ohm", "tau1_s", "r2_ohm", "tau2_s", "i0_a")


@dataclass(frozen=True)
class TemperatureTable:
    """What the HPPC and C/20 tests at one chamber temperature give."""

    ambient_c: float
    temperature_c: float  # mean cell temperature during the HPPC pulses
    ocv: OcvCurve
    charge_ah: Array  # charge removed at each HPPC state of charge
    values: dict[str, Array] = field(repr=False)

    def __post_init__(self) -> None:
        if set(self.values) != set(PARAMETERS):
            raise ValueError(f"expected parameters {PARAMETERS}")
        for name, column in self.values.items():
            if len(column) != len(self.charge_ah):
                raise ValueError(
                    f"{name} has {len(column)} values for {len(self.charge_ah)} states"
                )
            if np.any(column <= 0):
                raise ValueError(f"{name} must be positive")
        if np.any(np.diff(self.charge_ah) <= 0):
            raise ValueError("charge_ah must increase")


def _bracket(temperatures: Array, t_c: Array) -> tuple[Index, Index, Array]:
    """Indices of the tables below and above each temperature, and the weight of the upper one
    in 1/T (Kelvin), held to [0, 1] outside the range."""
    t_c = np.clip(t_c, temperatures[0], temperatures[-1])
    hi: Index = np.clip(np.searchsorted(temperatures, t_c), 1, len(temperatures) - 1)
    lo: Index = hi - 1
    inv = 1.0 / (np.asarray(t_c) + KELVIN)
    inv_lo = 1.0 / (temperatures[lo] + KELVIN)
    inv_hi = 1.0 / (temperatures[hi] + KELVIN)
    weight = (inv - inv_lo) / (inv_hi - inv_lo)
    return lo, hi, weight


@dataclass(frozen=True)
class CellModel:
    tables: tuple[TemperatureTable, ...]

    def __post_init__(self) -> None:
        temps = [t.temperature_c for t in self.tables]
        if len(temps) < 2 or np.any(np.diff(temps) <= 0):
            raise ValueError("tables must be at two or more increasing temperatures")

    @property
    def temperatures_c(self) -> Array:
        return np.array([t.temperature_c for t in self.tables])

    @property
    def charge_limit_ah(self) -> Array:
        """How far each temperature's open-circuit voltage curve reaches, in Ah removed."""
        return np.array([t.ocv.charge_ah[-1] for t in self.tables])

    def ocv_v(self, charge_ah: Array | float, temperature_c: Array | float) -> Array:
        q = np.atleast_1d(np.asarray(charge_ah, dtype=float))
        t_c = np.broadcast_to(np.asarray(temperature_c, dtype=float), q.shape)
        temps = self.temperatures_c
        t_c = np.clip(t_c, temps[0], temps[-1])
        hi = np.clip(np.searchsorted(temps, t_c), 1, len(temps) - 1)
        lo = hi - 1
        weight = (t_c - temps[lo]) / (temps[hi] - temps[lo])
        at = np.stack([table.ocv(q) for table in self.tables])
        cols = np.arange(len(q))
        return np.asarray((1 - weight) * at[lo, cols] + weight * at[hi, cols], dtype=float)

    def parameters(
        self, charge_ah: Array | float, temperature_c: Array | float
    ) -> dict[str, Array]:
        q = np.atleast_1d(np.asarray(charge_ah, dtype=float))
        t_c = np.broadcast_to(np.asarray(temperature_c, dtype=float), q.shape)
        lo, hi, weight = _bracket(self.temperatures_c, t_c)
        cols = np.arange(len(q))
        out = {}
        for name in PARAMETERS:
            logs = np.stack(
                [np.log(np.interp(q, t.charge_ah, t.values[name])) for t in self.tables]
            )
            out[name] = np.exp((1 - weight) * logs[lo, cols] + weight * logs[hi, cols])
        return out


def charge_transfer_v(current_a: Array, temperature_c: Array, i0_a: Array) -> Array:
    """Butler-Volmer overpotential, symmetric (alpha = 1/2), in volts."""
    thermal = 2 * GAS_CONSTANT * (np.asarray(temperature_c) + KELVIN) / FARADAY
    return np.asarray(thermal * np.arcsinh(np.asarray(current_a) / (2 * np.asarray(i0_a))))


def rc_response(dt_s: Array, current_a: Array, r_ohm: Array, tau_s: Array) -> Array:
    """Voltage of an RC pair driven by a held current, starting at rest.

    u[0] = 0; u[n+1] = a u[n] + R (1 - a) i[n], a = exp(-dt[n] / tau[n]); R and tau may vary
    from step to step. dt has one element less than the current.
    """
    n = len(current_a)
    if len(dt_s) != n - 1:
        raise ValueError("dt must have one element less than the current")
    a = np.exp(-np.asarray(dt_s) / np.broadcast_to(tau_s, (n,))[:-1])
    b = (np.broadcast_to(r_ohm, (n,))[:-1] * (1 - a) * np.asarray(current_a)[:-1]).tolist()
    a_list = a.tolist()
    u = [0.0] * n
    value = 0.0
    for k in range(n - 1):
        value = a_list[k] * value + b[k]
        u[k + 1] = value
    return np.array(u)


@dataclass(frozen=True)
class Simulation:
    time_s: Array
    current_a: Array
    temperature_c: Array
    charge_ah: Array
    ocv_v: Array
    ohmic_v: Array
    charge_transfer_v: Array
    rc1_v: Array
    rc2_v: Array

    @property
    def voltage_v(self) -> Array:
        return np.asarray(
            self.ocv_v + self.ohmic_v + self.charge_transfer_v + self.rc1_v + self.rc2_v
        )

    @property
    def heat_w(self) -> Array:
        """Heat released in the cell by its losses: current times the overpotential."""
        return np.asarray(self.current_a * (self.voltage_v - self.ocv_v))


def simulate_current(
    model: CellModel,
    time_s: Array,
    current_a: Array,
    temperature_c: Array | float,
    initial_charge_ah: float = 0.0,
) -> Simulation:
    """Terminal voltage for a given current, starting at rest with initial_charge_ah removed.

    The charge removed is counted with the trapezoid rule, as for the measurements.
    """
    time_s = np.asarray(time_s, dtype=float)
    current_a = np.asarray(current_a, dtype=float)
    t_c = np.broadcast_to(np.asarray(temperature_c, dtype=float), time_s.shape).astype(float)
    steps = np.diff(time_s) * (current_a[1:] + current_a[:-1]) / 2
    charge = initial_charge_ah - np.concatenate(([0.0], np.cumsum(steps))) / 3600
    p = model.parameters(charge, t_c)
    dt = np.diff(time_s)
    return Simulation(
        time_s=time_s,
        current_a=current_a,
        temperature_c=t_c,
        charge_ah=charge,
        ocv_v=model.ocv_v(charge, t_c),
        ohmic_v=p["r0_ohm"] * current_a,
        charge_transfer_v=charge_transfer_v(current_a, t_c, p["i0_a"]),
        rc1_v=rc_response(dt, current_a, p["r1_ohm"], p["tau1_s"]),
        rc2_v=rc_response(dt, current_a, p["r2_ohm"], p["tau2_s"]),
    )


def _current_for_power(
    power_w: float, emf_v: float, r0: float, thermal_v: float, i0: float
) -> float | None:
    """Current (charge positive) at which v(i) i = power, v(i) = emf + r0 i + eta(i).

    On discharge (power < 0) the delivered power |v i| rises with |i| up to a maximum and then
    falls; the smaller-current root is the physical one. Returns None if the cell cannot
    deliver the power.
    """
    if power_w == 0:
        return 0.0

    def g(i: float) -> float:
        return (emf_v + r0 * i + thermal_v * math.asinh(i / (2 * i0))) * i - power_w

    def dg(i: float) -> float:
        slope = r0 + thermal_v / math.sqrt((2 * i0) ** 2 + i * i)
        return emf_v + r0 * i + thermal_v * math.asinh(i / (2 * i0)) + i * slope

    i = power_w / emf_v
    for _ in range(50):
        step = g(i) / dg(i)
        i_next = i - step
        if power_w < 0 and dg(i_next) <= 0:  # past the maximum-power point: no solution
            return None
        if abs(step) < 1e-9:
            return i_next
        i = i_next
    return None  # pragma: no cover - on this monotone branch Newton converges in a few steps


def simulate_power(
    model: CellModel,
    power_w: Array,
    dt_s: float,
    temperature_c: float,
    *,
    initial_charge_ah: float = 0.0,
    min_voltage_v: float = 2.8,
    max_charge_a: float = math.inf,
    max_voltage_v: float = 4.2,
    voltage_floor: bool = False,
) -> Simulation:
    """Run a power demand (positive on charge) until the voltage would fall below
    min_voltage_v, the cell cannot deliver the power, or the demand ends.

    The current of each step is the one that gives the demanded power at the terminals with
    the RC voltages of the start of the step; it is held over the step. This is how the tests
    of the dataset drove the cell: with a power profile, not a current profile. Charging
    (regenerative braking) is capped at max_charge_a, as the tests capped it in the cold, and
    at the current that holds the cell at max_voltage_v, its charge voltage.

    With voltage_floor=True a demand the cell cannot meet above min_voltage_v does not end the
    run: the current is reduced to the value that holds the cell at min_voltage_v, as a cycler
    does, and the run ends only when the cell cannot hold that voltage even without current.
    """
    power = np.asarray(power_w, dtype=float)
    limit = float(np.interp(temperature_c, model.temperatures_c, model.charge_limit_ah))
    # The temperature is constant, so the parameters depend on q alone: tabulate them once on a
    # grid finer than the open-circuit voltage curve's own (5 mAh) and interpolate from it.
    grid = np.linspace(0.0, limit, 2001)
    table = model.parameters(grid, temperature_c)
    ocv_table = model.ocv_v(grid, temperature_c)
    q = initial_charge_ah
    u1 = u2 = 0.0
    thermal = 2 * GAS_CONSTANT * (temperature_c + KELVIN) / FARADAY
    rows: list[tuple[float, ...]] = []
    for k, demand in enumerate(power.tolist()):
        p = {name: float(np.interp(q, grid, column)) for name, column in table.items()}
        ocv = float(np.interp(q, grid, ocv_table))
        emf = ocv + u1 + u2

        def terminal(current: float, emf: float = emf, p: dict[str, float] = p) -> float:
            return emf + p["r0_ohm"] * current + thermal * math.asinh(current / (2 * p["i0_a"]))

        def current_at(voltage: float, low: float, high: float) -> float:
            """The current in [low, high] at which the terminal voltage is `voltage`
            (bisection; the voltage rises with the current)."""
            for _ in range(60):
                mid = (low + high) / 2
                low, high = (mid, high) if terminal(mid) < voltage else (low, mid)
            return (low + high) / 2

        found = _current_for_power(demand, emf, p["r0_ohm"], thermal, p["i0_a"])
        if found is None or (demand < 0 and terminal(found) < min_voltage_v):
            if not voltage_floor or emf <= min_voltage_v:
                break
            i = current_at(min_voltage_v, -emf / p["r0_ohm"], 0.0)
        else:
            i = min(found, max_charge_a)
        if i > 0 and terminal(i) > max_voltage_v:
            # Charging would lift the cell above its charge voltage: hold it there.
            i = current_at(max_voltage_v, 0.0, i)
        eta = thermal * math.asinh(i / (2 * p["i0_a"]))
        rows.append((k * dt_s, i, q, ocv, p["r0_ohm"] * i, eta, u1, u2))
        q_next = q - i * dt_s / 3600
        if q_next > limit:
            break
        a1 = math.exp(-dt_s / p["tau1_s"])
        a2 = math.exp(-dt_s / p["tau2_s"])
        u1 = a1 * u1 + p["r1_ohm"] * (1 - a1) * i
        u2 = a2 * u2 + p["r2_ohm"] * (1 - a2) * i
        q = q_next
    data = np.array(rows, dtype=float).reshape(-1, 8)
    return Simulation(
        time_s=data[:, 0],
        current_a=data[:, 1],
        temperature_c=np.full(len(data), temperature_c),
        charge_ah=data[:, 2],
        ocv_v=data[:, 3],
        ohmic_v=data[:, 4],
        charge_transfer_v=data[:, 5],
        rc1_v=data[:, 6],
        rc2_v=data[:, 7],
    )

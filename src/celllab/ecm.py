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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq

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
        # Summed in the order step_current sums them, (OCV + u1 + u2) + R0 i + eta, so that a
        # voltage it holds at a limit is the voltage recorded, to the last bit.
        return np.asarray(
            self.ocv_v + self.rc1_v + self.rc2_v + self.ohmic_v + self.charge_transfer_v
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


def _root(f: Callable[[float], float], low: float, high: float) -> float:
    """The root of f in [low, high], where f changes sign (Brent's method, which falls back
    on bisection and so always converges)."""
    return float(brentq(f, low, high, xtol=1e-12))


def _bisect(f: Callable[[float], float], low: float, high: float) -> tuple[float, float]:
    """Narrow [low, high], over which f rises through 0, by 60 halvings (to the precision of a
    float), keeping f(low) <= 0 < f(high): each end stays on its own side of the root."""
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if f(mid) <= 0 else (low, mid)
    return low, high


@dataclass(frozen=True)
class Limits:
    """What the cycler allows: the voltage range and the current either way."""

    min_voltage_v: float = 2.8
    max_voltage_v: float = 4.2
    max_charge_a: float = math.inf
    max_discharge_a: float = math.inf
    voltage_floor: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.min_voltage_v < self.max_voltage_v:
            raise ValueError("the voltage range must be positive and not empty")
        if self.max_charge_a <= 0 or self.max_discharge_a <= 0:
            raise ValueError("the current limits must be positive")


DEFAULT_LIMITS = Limits()  # the cell's voltage range, 2.8 to 4.2 V, and no current limit


@dataclass(frozen=True)
class _Terminal:
    """The terminal voltage over one step: v(i) = emf + r0 i + thermal asinh(i / (2 i0))."""

    emf_v: float
    r0: float
    thermal_v: float
    i0: float

    def voltage(self, i: float) -> float:
        return self.emf_v + self.r0 * i + self.thermal_v * math.asinh(i / (2 * self.i0))

    def power(self, i: float) -> float:
        return self.voltage(i) * i

    def slope(self, i: float) -> float:
        """d(power)/di."""
        conductance = self.r0 + self.thermal_v / math.sqrt((2 * self.i0) ** 2 + i * i)
        return self.voltage(i) + i * conductance


def step_current(
    power_w: float, emf_v: float, r0: float, thermal_v: float, i0: float, *, limits: Limits
) -> float | None:
    """The current (charge positive) that gives power_w at the terminals, within the limits;
    None if the run must end.

    The terminal voltage v(i) = emf + r0 i + thermal asinh(i / (2 i0)) rises with i, and the
    power p(i) = v(i) i is convex in i. On charge, p rises from 0 without bound and exceeds
    power_w at i = power_w / emf, where v > emf: one root lies in between. On discharge, p
    falls from 0 to its minimum, the most power the cell can give, where dp/di = 0, and rises
    beyond it; the physical current is the root on the near side of that point. A root with
    v >= min_voltage_v has |i| = |power_w| / v <= |power_w| / min_voltage_v, so it is looked
    for only that far, and no further than max_discharge_a.

    A charge is capped at max_charge_a and at the current that holds max_voltage_v (no current
    if the cell is already above it). If a discharge cannot be given within the limits, the
    cycler holds the current limit, max_discharge_a, or the voltage limit, min_voltage_v,
    whichever it reaches first; at the voltage limit it does so only with voltage_floor=True,
    and otherwise the run ends. It also ends when the cell is at or below min_voltage_v without
    current.
    """
    cell = _Terminal(emf_v, r0, thermal_v, i0)
    if power_w > 0:
        return _charge(cell, power_w, limits)
    if power_w < 0:
        return _discharge(cell, power_w, limits)
    return 0.0


def _charge(cell: _Terminal, power_w: float, limits: Limits) -> float:
    i = min(
        _root(lambda c: cell.power(c) - power_w, 0.0, power_w / cell.emf_v), limits.max_charge_a
    )
    if cell.voltage(i) <= limits.max_voltage_v:
        return i
    if cell.emf_v >= limits.max_voltage_v:
        return 0.0
    # The current that holds max_voltage_v, from below: the voltage never exceeds it.
    return _bisect(lambda c: cell.voltage(c) - limits.max_voltage_v, 0.0, i)[0]


def _discharge(cell: _Terminal, power_w: float, limits: Limits) -> float | None:
    if cell.emf_v <= limits.min_voltage_v:
        return None
    reach = max(power_w / limits.min_voltage_v, -limits.max_discharge_a)
    # The physical root lies between 0 and the maximum-power point, if that comes first.
    near = reach if cell.slope(reach) >= 0 else _root(cell.slope, reach, 0.0)
    if cell.power(near) <= power_w:
        return _root(lambda c: cell.power(c) - power_w, near, 0.0)
    # The power is out of reach. The current that holds min_voltage_v lies between 0 and
    # -emf / r0, where v < 0; it is taken from above, so the voltage never falls below it.
    lowest = -cell.emf_v / cell.r0
    floor = _bisect(lambda c: cell.voltage(c) - limits.min_voltage_v, lowest, 0.0)[1]
    if -limits.max_discharge_a >= floor:
        return -limits.max_discharge_a
    return floor if limits.voltage_floor else None


def simulate_power(
    model: CellModel,
    power_w: Array,
    dt_s: float,
    temperature_c: float,
    *,
    initial_charge_ah: float = 0.0,
    limits: Limits = DEFAULT_LIMITS,
) -> Simulation:
    """Run a power demand (positive on charge) until the cell cannot meet it within the
    limits (step_current), the charge removed reaches the end of the open-circuit voltage
    curve, or the demand ends.

    The current of each step is the one that gives the demanded power at the terminals with
    the RC voltages of the start of the step; it is held over the step. This is how the tests
    of the dataset drove the cell: with a power profile, not a current profile, within limits
    on the current either way and on the voltage.
    """
    power = np.asarray(power_w, dtype=float)
    limit = float(np.interp(temperature_c, model.temperatures_c, model.charge_limit_ah))
    # The temperature is constant, so the parameters depend on q alone: tabulate them once on a
    # grid finer than the open-circuit voltage curve's own (5 mAh) and interpolate linearly
    # from it, holding the values at its ends, as np.interp does.
    points = 2001
    grid = np.linspace(0.0, limit, points)
    columns = model.parameters(grid, temperature_c)
    table = np.column_stack(
        [columns[name] for name in PARAMETERS] + [model.ocv_v(grid, temperature_c)]
    ).tolist()
    spacing = limit / (points - 1)
    q = initial_charge_ah
    u1 = u2 = 0.0
    thermal = 2 * GAS_CONSTANT * (temperature_c + KELVIN) / FARADAY
    rows: list[tuple[float, ...]] = []
    for k, demand in enumerate(power.tolist()):
        x = min(max(q / spacing, 0.0), points - 1.0)
        j = min(int(x), points - 2)
        w = x - j
        r0, r1, tau1, r2, tau2, i0, ocv = (
            a + w * (b - a) for a, b in zip(table[j], table[j + 1], strict=True)
        )
        found = step_current(demand, ocv + u1 + u2, r0, thermal, i0, limits=limits)
        if found is None:
            break
        i = found
        eta = thermal * math.asinh(i / (2 * i0))
        rows.append((k * dt_s, i, q, ocv, r0 * i, eta, u1, u2))
        q_next = q - i * dt_s / 3600
        if q_next > limit:
            break
        a1 = math.exp(-dt_s / tau1)
        a2 = math.exp(-dt_s / tau2)
        u1 = a1 * u1 + r1 * (1 - a1) * i
        u2 = a2 * u2 + r2 * (1 - a2) * i
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

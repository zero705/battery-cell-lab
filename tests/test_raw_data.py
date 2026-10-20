"""Every number the code comments and documents state about the raw data, recomputed from it.

These tests need the raw data (python tools/fetch_dataset.py) and are skipped without it.
"""

from __future__ import annotations

import functools
import itertools
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import scipy.io
from conftest import REPORT_RESISTANCE_MOHM, raw
from scipy.interpolate import PchipInterpolator

from celllab import catalog, identify, lab, ocv
from celllab.catalog import DatasetFile
from celllab.measurements import Measurement, read_mat
from celllab.model_file import read

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import audit_dataset  # noqa: E402
from validate_model import PERIOD_S, PROFILE_FOLDER  # noqa: E402

import streamlit_app  # noqa: E402

pytestmark = raw


def _flat(name: str) -> str:
    """A document with its line breaks as spaces, so that a phrase may span lines."""
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


README, METHOD, DATA_MD = _flat("README.md"), _flat("docs/method.md"), _flat("docs/data.md")
MEASUREMENTS = _flat("src/celllab/measurements.py")


@functools.cache
def _read(folder: str, kind: str) -> Measurement:
    return read_mat(catalog.find(folder, kind).path)


def _hppc(folder: str) -> Measurement:
    return _read(folder, "HPPC")


def _c20(folder: str) -> Measurement:
    return _read(folder, "C20DisCh")


def _drives(folder: str | None = None) -> list[tuple[DatasetFile, Measurement]]:
    """The usable drive-cycle tests, of one folder or all."""
    return [
        (c, _read(c.folder, c.kind))
        for c in catalog.drive_cycles()
        if folder is None or c.folder == folder
    ]


def _power(m: Measurement, seconds: float) -> np.ndarray:
    """The power at the terminals, W, every second over the first `seconds`."""
    t = np.arange(0.0, seconds, 1.0)
    return np.asarray(np.interp(t, m.time_s, m.voltage_v * m.current_a))


def test_ocv_constructions_compared_by_leave_one_out() -> None:
    hybrid, rest_only, lines = [], [], []
    for folder in catalog.AMBIENT_C:
        hppc, c20 = _hppc(folder), _c20(folder)
        errors = ocv.leave_one_out(hppc, c20)
        hybrid += errors.tolist()
        # The largest error is at one of the three lowest states of charge predicted.
        assert int(np.argmax(np.abs(errors))) >= len(errors) - 3, folder
        points = ocv.rest_points(hppc)
        q = np.array([p.charge_ah for p in points])
        v = np.array([p.voltage_v for p in points])
        for k in range(1, len(points) - 1):
            keep = np.r_[0:k, k + 1 : len(points)]
            rest_only.append(float(PchipInterpolator(q[keep], v[keep])(q[k]) - v[k]))
            lines.append(float(np.interp(q[k], q[keep], v[keep]) - v[k]))

    def rms(errors: list[float]) -> float:
        return float(np.sqrt(np.mean(np.square(errors)))) * 1e3

    def largest(errors: list[float]) -> float:
        return float(np.max(np.abs(errors))) * 1e3

    assert len(hybrid) == len(rest_only) == len(lines) == 56
    assert (round(rms(hybrid), 1), round(largest(hybrid))) == (8.9, 42)
    assert (round(rms(rest_only), 1), round(largest(rest_only))) == (17.8, 40)
    assert (round(rms(lines), 1), round(largest(lines))) == (25.6, 70)
    for label, construction in (
        ("rest points alone", rest_only),
        ("Straight lines between the rest points", lines),
    ):
        assert f"{label} | {rms(construction):.1f} mV | {largest(construction):.0f} mV |" in METHOD
    assert f"A curve through the rest points alone gets {rms(rest_only):.1f} mV" in README
    stored = read()["ocv_leave_one_out"]
    assert stored["rms_mv"] == pytest.approx(rms(hybrid), rel=1e-5)
    assert stored["max_abs_mv"] == pytest.approx(largest(hybrid), rel=1e-5)


def test_c20_noise_is_only_at_minus_20_and_small() -> None:
    for folder in catalog.AMBIENT_C:
        c20 = _c20(folder)
        k = np.flatnonzero(c20.current_a < ocv.C20_DISCHARGE_A)
        rises = np.diff(c20.voltage_v[k])
        cleaned = ocv.c20_discharge(c20)[1]
        change = np.max(np.abs(cleaned - c20.voltage_v[k]))
        if folder == "n20degC":
            assert int(np.sum(rises > 0)) == 51
            assert rises.max() * 1e3 == pytest.approx(0.34, abs=0.005)
            assert change * 1e3 == pytest.approx(0.28, abs=0.005)
        else:
            assert np.all(rises <= 0)
            assert change == 0.0


def test_c20_charge_and_discharge_counts_disagree_by_up_to_019_ah() -> None:
    gaps = []
    for folder in catalog.AMBIENT_C:
        c20 = _c20(folder)
        q = c20.charge_removed_ah
        dis = np.flatnonzero(c20.current_a < -0.05)
        ch = np.flatnonzero(c20.current_a > 0.01)
        gaps.append(abs((q[ch[0]] - q[ch[-1]]) - (q[dis[-1]] - q[dis[0]])))
    assert max(gaps) == pytest.approx(0.19, abs=0.005)


def test_c20_and_hppc_capacities() -> None:
    for folder in catalog.AMBIENT_C:
        c20 = _c20(folder)
        k = np.flatnonzero(c20.current_a < ocv.C20_DISCHARGE_A)
        assert round(float(-np.median(c20.current_a[k])), 2) == 0.15, folder
        hppc = _hppc(folder)
        steps = [
            (a, b)
            for a, b in identify._runs(hppc.current_a < -0.05)
            if hppc.time_s[b - 1] - hppc.time_s[a] > identify.STEP_S
        ]
        currents = [float(-np.median(hppc.current_a[a:b])) for a, b in steps]
        assert min(currents) > 0.865, folder
        assert max(currents) < 0.905, folder
    assert "The HPPC steps, at 0.87 to 0.9 A, agree with the C/20 discharge" in METHOD
    warm = float(ocv.c20_discharge(_c20("25degC"))[0][-1])
    hot = float(ocv.c20_discharge(_c20("40degC"))[0][-1])
    assert f"removed {hot:.3f} Ah, against {warm:.3f} Ah at 25 °C" in README
    assert f"removed {hot:.3f} Ah at 40 °C and {warm:.3f} Ah at 25 °C" in DATA_MD
    # The 25 degC HPPC test ends with a step to 2.8 V.
    hppc = _hppc("25degC")
    _, end = identify._runs(hppc.current_a < -0.05)[-1]
    assert hppc.voltage_v[end - 1] <= 2.8 + 1e-3
    step = float(hppc.charge_removed_ah[end - 1])
    assert f"they remove {step:.3f} and {warm:.3f} Ah" in METHOD
    assert round(step, 2) == round(warm, 2) == 2.78  # "both remove 2.78 Ah", celllab/ocv.py


def test_hppc_rests_and_pulses() -> None:
    model = read()
    discharge = {
        "n20degC": [0.75, 1.5, 3.0, 6.0],
        "n10degC": [1.5, 3.0, 6.0, 12.0],
        "0degC": [3.0, 6.0, 12.0, 18.0],
        "10degC": [2.9, 5.8, 11.6, 17.4],
        "25degC": [3.0, 6.0, 12.0, 18.0],
        "40degC": [3.0, 6.0, 12.0, 18.0],
    }
    largest_charge = {
        "n20degC": 1.5,
        "n10degC": 3.0,
        "0degC": 3.0,
        "10degC": 5.8,
        "25degC": 6.0,
        "40degC": 6.0,
    }
    for entry, folder in zip(model["temperatures"], catalog.AMBIENT_C, strict=True):
        hppc = _hppc(folder)
        points = ocv.rest_points(hppc)
        assert len(points) == len(entry["rest_points"])
        sets, charges = [], []
        for start, stop in identify.windows(hppc, points):
            i, t = hppc.current_a[start:stop], hppc.time_s[start:stop]
            pulses = [
                round(float(-np.median(i[a:b])), 2)
                for a, b in identify._runs(i < -0.05)
                if t[b - 1] - t[a] < identify.STEP_S
            ]
            sets.append(tuple(pulses))
            for a, b in identify._runs(i > 0.05):
                assert t[b - 1] - t[a] < 10.0, folder  # every charge is a pulse of 10 s
                charges.append(round(float(np.median(i[a:b])), 2))
        assert list(Counter(sets).most_common(1)[0][0]) == discharge[folder]
        assert max(charges) == largest_charge[folder]
        if folder == "n20degC":
            charging = np.concatenate(
                [hppc.current_a[a:b] for a, b in identify.windows(hppc, points)]
            )
            assert charging.max() < 1.51  # the cold cell is charged at 1.5 A at most
            assert "in the short 10 s pulses of the HPPC test, at most 1.5 A" in README
    # The timing of a pulse pair, at the second state of charge at 25 degC.
    hppc = _hppc("25degC")
    start, stop = identify.windows(hppc, ocv.rest_points(hppc))[1]
    i, t = hppc.current_a[start:stop], hppc.time_s[start:stop]
    state = np.sign(np.where(np.abs(i) > 0.05, i, 0.0))
    change = np.flatnonzero(np.diff(state)) + 1
    bounds = np.concatenate(([0], change, [len(i)]))
    lengths = [round(float(t[b - 1] - t[a])) for a, b in itertools.pairwise(bounds)]
    assert lengths[1:5] == [10, 40, 10, 610]  # discharge, rest, charge, rest (to the sample)


def test_ten_second_resistances_match_the_dataset_authors_report() -> None:
    """The report's pulse currents: 0.25C at -20 degC, 0.5C at -10 degC, 1C above (1C = 3 A,
    2.9 A at 10 degC)."""
    amps = {"n20degC": 0.75, "n10degC": 1.5, "0degC": 3.0, "10degC": 2.9, "25degC": 3.0}
    amps["40degC"] = 3.0
    found = {}
    for folder, current in amps.items():
        h = _hppc(folder)
        q = h.charge_removed_ah
        starts = np.flatnonzero(np.diff((h.current_a < -0.05).astype(int)) == 1) + 1
        for s in starts:
            if abs(abs(h.current_a[s + 5]) - current) < 0.1 and abs(q[s] - 1.5) < 0.05:
                end = s + int(np.flatnonzero(h.current_a[s:] > -0.05)[0]) - 1
                found[folder] = (h.voltage_v[end] - h.voltage_v[s - 1]) / h.current_a[s + 5] * 1e3
                break
    assert set(found) == set(REPORT_RESISTANCE_MOHM)
    for folder, mohm in REPORT_RESISTANCE_MOHM.items():
        if folder == "10degC":
            above = found[folder] - mohm
            assert f"At 10 °C I get {found[folder]:.1f} mΩ, {above:.1f} mΩ higher than" in README
            assert f"pulse gives {found[folder]:.1f} mΩ, {above:.1f} mΩ above the report" in METHOD
        else:
            assert found[folder] == pytest.approx(mohm, abs=0.5), folder


def test_profile_periods_are_the_autocorrelation_peaks() -> None:
    for kind, period in PERIOD_S.items():
        m = _read(PROFILE_FOLDER, kind)
        p = _power(m, m.time_s[-1])
        x = (p - p.mean())[:6000]
        ac = np.correlate(x, x, mode="full")[len(x) - 1 :]
        assert int(np.argmax(ac[300:2500])) + 300 == period, kind


def test_the_other_temperatures_follow_the_40_degree_profiles() -> None:
    correlations = []
    for test, m in _drives():
        if test.kind in PERIOD_S and test.folder != PROFILE_FOLDER:
            period = PERIOD_S[test.kind]
            reference = _power(_read(PROFILE_FOLDER, test.kind), period)
            correlations.append(float(np.corrcoef(_power(m, period), reference)[0, 1]))
    assert len(correlations) == 18
    low, high = min(correlations), max(correlations)
    assert f"(correlation {low:.2f} to {high:.3f} with the 40 °C test" in METHOD


def test_cold_us06_share_measured() -> None:
    """In the -20 degC US06 test the current limit, not the 2.8 V floor, held the cell back in
    the first period: it gave 82 % of the discharge energy the 40 degC test shows."""
    period = PERIOD_S["US06"]
    cold = _read("n20degC", "US06")
    demand = _power(_read("40degC", "US06"), period)
    given = _power(cold, period)
    share = np.minimum(given, 0.0).sum() / np.minimum(demand, 0.0).sum()
    assert round(float(share), 2) == streamlit_app.US06_COLD_SHARE_MEASURED
    first = cold.time_s < period
    assert cold.voltage_v[first].min() > 3.1
    held = np.abs(cold.current_a[first] + lab.discharge_limit_a(-20.0)) < 0.02
    assert held.sum() > 100  # samples 0.1 s apart: more than 10 s at the 6 A limit


def test_current_limits_of_the_drive_cycles() -> None:
    for folder, ambient in catalog.AMBIENT_C.items():
        current = np.concatenate([m.current_a for _, m in _drives(folder)])
        charge, discharge = current[current > 0.05], -current[current < -0.05]
        limit = lab.regen_limit_a(ambient)
        assert np.percentile(charge, 99.9) == pytest.approx(limit, abs=0.01), folder
        assert charge.max() < limit + 0.11, folder
        limit = lab.discharge_limit_a(ambient)
        if np.isfinite(limit):
            assert np.percentile(discharge, 99.9) == pytest.approx(limit, abs=0.01), folder
            assert np.sum(np.abs(discharge - limit) < 0.02) > 1000, folder
            assert discharge.max() < limit + 0.3, folder
        else:  # no value is held: the cell followed the demand, up to 18 A
            assert np.percentile(discharge, 99.9) < 0.85 * discharge.max(), folder
            assert round(float(discharge.max())) == 18, folder


def test_cold_tests_warm_the_cell_by_about_2_to_5_degrees() -> None:
    rises = [float(np.ptp(m.temperature_c)) for _, m in _drives("n20degC")]
    phrase = f"by about {min(rises):.0f} to {max(rises):.0f} °C in the -20 °C tests"
    assert phrase in README
    assert phrase in " ".join((ROOT / "streamlit_app.py").read_text(encoding="utf-8").split())


def test_unidentifiable_levels_are_the_lowest_at_10_25_and_40() -> None:
    dropped = {}
    for entry in read()["temperatures"]:
        levels = entry["variants"]["charge_transfer"]["levels"]
        bad = [lv for lv in levels if not lv["identifiable"]]
        if bad:
            assert bad == [levels[-1]]
            assert bad[0]["longest_rest_s"] == pytest.approx(610, abs=1)  # a 10-minute rest
            dropped[entry["folder"]] = bad[0]["tau2_s"]
    assert set(dropped) == {"10degC", "25degC", "40degC"}


def test_windows_of_the_real_tests() -> None:
    for folder in catalog.AMBIENT_C:
        h = _hppc(folder)
        points = ocv.rest_points(h)
        ranges = identify.windows(h, points)
        levels = read()["temperatures"][list(catalog.AMBIENT_C).index(folder)]
        assert len(ranges) == len(levels["variants"]["linear"]["levels"])


def test_the_audit_figures() -> None:
    """The figures of celllab/measurements.py and docs/data.md about every raw file."""
    repeated = same = files = 0
    dv = di = 0.0
    broken = []
    for path in sorted(catalog.RAW.rglob("*.mat")):
        meas = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)["meas"]
        t = np.atleast_1d(np.asarray(meas.Time, dtype=float))
        v = np.atleast_1d(np.asarray(meas.Voltage, dtype=float))
        i = np.atleast_1d(np.asarray(meas.Current, dtype=float))
        if np.isnan(t).any() or np.isnan(v).any() or np.any(np.diff(t) < 0):
            broken.append(path.name)
            continue
        k = np.flatnonzero(np.diff(t) == 0)
        if len(k):
            files += 1
            repeated += len(k)
            same += int(np.sum((v[k + 1] == v[k]) & (i[k + 1] == i[k])))
            dv = max(dv, float(np.max(np.abs(v[k + 1] - v[k]))))
            di = max(di, float(np.max(np.abs(i[k + 1] - i[k]))))
    assert broken == [catalog.find("10degC", "LA92").path.name]
    readable = len(list(catalog.RAW.rglob("*.mat"))) - len(broken)
    for text in (DATA_MD, MEASUREMENTS):
        assert (
            f"In the {readable} readable files, {repeated:,} rows in {files} files repeat the "
            f"previous time stamp; {same:,}"
        ) in text
        assert f"at most {dv * 1e3:.1f} mV and {di * 1e3:.0f} mA" in text
    udds = catalog.find("25degC", "UDDS").path
    wh = scipy.io.loadmat(udds, squeeze_me=True, struct_as_record=False)["meas"].Wh
    (value,) = set(np.atleast_1d(wh).tolist())
    m = _read("25degC", "UDDS")
    energy = float(abs(np.trapezoid(m.voltage_v * m.current_a, m.time_s))) / 3600
    assert (
        f"it reads {value} throughout the 25 °C UDDS test, which moves {energy:.1f} Wh" in DATA_MD
    )
    assert f"it reads {value} throughout the 25 degC UDDS test, which moves {energy:.1f} Wh" in (
        MEASUREMENTS
    )


def test_the_excluded_tests() -> None:
    hwfet = _read("25degC", "HWFET")
    assert hwfet.time_s[-1] == pytest.approx(600.0, abs=0.5)
    assert np.all(hwfet.current_a == 0)
    la92 = scipy.io.loadmat(
        catalog.find("10degC", "LA92").path, squeeze_me=True, struct_as_record=False
    )["meas"]
    t = np.asarray(la92.Time, dtype=float)
    columns = [np.asarray(c, dtype=float) for c in (la92.Voltage, la92.Current)]
    assert int(np.sum(np.diff(t) < 0)) == 4
    assert not np.isnan(t).any()
    assert all(int(np.isnan(c).sum()) == 3 for c in columns)
    for n in range(4, 9):
        m = _read("40degC", f"Mixed{n}")
        assert round(float(m.temperature_c.mean())) in {23, 24}
        assert round(float(m.charge_removed_ah[-1]), 2) == 0.19
    # -10 degC Mixed4: one gap in the logging while the cycle runs.
    mixed4 = _read("n10degC", "Mixed4")
    (k,) = audit_dataset.logging_gaps(mixed4)
    gap, start = mixed4.time_s[k + 1] - mixed4.time_s[k], mixed4.time_s[k]
    reason = f"nothing is logged for {gap:.0f} s from {start:.0f} s into the test"
    assert catalog.EXCLUDED[("n10degC", "Mixed4")].startswith(reason)
    assert reason in DATA_MD
    assert f"nothing is logged for {gap:.0f} s, from {start:.0f} s into the test" in DATA_MD
    assert start / mixed4.time_s[-1] < 0.1  # "early in the drive"
    assert f"Mixed4 at -10 °C has a {gap:.0f} s gap in its log early in the drive" in README
    before, after = mixed4.voltage_v[k], mixed4.voltage_v[k + 1]
    assert f"the voltage falls from {before:.3f} to {after:.3f} V" in DATA_MD
    others = [
        float(_read("n10degC", f"Mixed{n}").charge_removed_ah[-1]) for n in (1, 2, 3, 5, 6, 7, 8)
    ]
    deficit = min(others) - float(mixed4.charge_removed_ah[-1])
    assert f"ends with {deficit:.2f} Ah less removed than the least of the other seven" in DATA_MD
    # No usable test has such a gap.
    assert all(not audit_dataset.logging_gaps(m) for _, m in _drives())


def test_the_drive_cycles_are_logged_every_tenth_of_a_second() -> None:
    for test, m in _drives():
        assert float(np.median(np.diff(m.time_s))) == pytest.approx(0.1, abs=0.002), test.kind
    assert "every sample (logged every 0.1 s)" in README
    assert "The drive cycles are logged every 0.1 s" in DATA_MD


def test_the_largest_current_in_the_data() -> None:
    largest = 0.0
    for path in sorted(catalog.RAW.rglob("*.mat")):
        try:
            m = read_mat(path)
        except ValueError:
            continue
        largest = max(largest, float(np.max(np.abs(m.current_a))))
    assert round(largest, 1) == 18.1  # below the 20 A of identify.NO_CHARGE_TRANSFER_A's note

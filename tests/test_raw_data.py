"""Every number the code comments and documents state about the raw data, recomputed from it.

These tests need the raw data (python tools/fetch_dataset.py) and are skipped without it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import raw
from scipy.interpolate import PchipInterpolator

from celllab import catalog, identify, lab, ocv
from celllab.ecm import CellModel
from celllab.measurements import Measurement, read_mat
from celllab.model_file import read

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from validate_model import PERIOD_S, PROFILE_FOLDER

pytestmark = raw


def _hppc(folder: str) -> Measurement:
    return read_mat(catalog.find(folder, "HPPC").path)


def _c20(folder: str) -> Measurement:
    return read_mat(catalog.find(folder, "C20DisCh").path)


def test_ocv_construction_beats_a_curve_through_the_rest_points_alone() -> None:
    hybrid, rest_only = [], []
    for folder in catalog.AMBIENT_C:
        hppc, c20 = _hppc(folder), _c20(folder)
        hybrid += ocv.leave_one_out(hppc, c20).tolist()
        points = ocv.rest_points(hppc)
        q = np.array([p.charge_ah for p in points])
        v = np.array([p.voltage_v for p in points])
        for k in range(1, len(points) - 1):
            keep = np.r_[0:k, k + 1 : len(points)]
            rest_only.append(float(PchipInterpolator(q[keep], v[keep])(q[k]) - v[k]))

    def rms(errors: list[float]) -> float:
        return float(np.sqrt(np.mean(np.square(errors)))) * 1e3

    assert round(rms(hybrid), 1) == 8.9
    assert round(rms(rest_only), 1) == 17.8
    assert read()["ocv_leave_one_out"]["rms_mv"] == pytest.approx(rms(hybrid), rel=1e-5)


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


def test_ten_second_resistances_match_the_dataset_authors_report() -> None:
    """The dataset's technical report gives the 10 s discharge resistance at 50 % state of
    charge; its pulse currents: 0.25C at -20 degC, 0.5C at -10 degC, 1C above (1C = 3 A)."""
    # At 10 degC the report gives 36.7 mOhm; the 1C pulse there reads 38.0 (docs/method.md).
    report = {
        "n20degC": (0.75, 179.3),
        "n10degC": (1.5, 89.8),
        "0degC": (3.0, 53.0),
        "10degC": (2.9, 38.0),
        "25degC": (3.0, 27.2),
        "40degC": (3.0, 23.6),
    }
    for folder, (amps, expected_mohm) in report.items():
        h = _hppc(folder)
        q = h.charge_removed_ah
        starts = np.flatnonzero(np.diff((h.current_a < -0.05).astype(int)) == 1) + 1
        found = []
        for s in starts:
            if abs(abs(h.current_a[s + 5]) - amps) < 0.1 and abs(q[s] - 1.5) < 0.05:
                end = s + int(np.flatnonzero(h.current_a[s:] > -0.05)[0]) - 1
                found.append((h.voltage_v[end] - h.voltage_v[s - 1]) / h.current_a[s + 5] * 1e3)
        assert found, folder
        assert found[0] == pytest.approx(expected_mohm, abs=0.5), folder


def test_profile_periods_are_the_autocorrelation_peaks() -> None:
    for kind, period in PERIOD_S.items():
        m = read_mat(catalog.find(PROFILE_FOLDER, kind).path)
        t = np.arange(0.0, m.time_s[-1], 1.0)
        p = np.interp(t, m.time_s, m.voltage_v * m.current_a)
        x = (p - p.mean())[:6000]
        ac = np.correlate(x, x, mode="full")[len(x) - 1 :]
        assert int(np.argmax(ac[300:2500])) + 300 == period, kind


def test_cold_us06_share_measured_and_modelled(model: CellModel) -> None:
    """In the -20 degC US06 test the cell gave 82 % of the first period's discharge power the
    40 degC test (where it followed the demand) shows; the lab's model gives 87 %."""
    period = 601
    measured = {}
    for folder in ("40degC", "n20degC"):
        m = read_mat(catalog.find(folder, "US06").path)
        t = np.arange(0.0, period, 1.0)
        measured[folder] = np.interp(t, m.time_s, m.voltage_v * m.current_a)
    demand = measured["40degC"] < 0
    ratio = measured["n20degC"][demand].mean() / measured["40degC"][demand].mean()
    assert ratio == pytest.approx(0.82, abs=0.005)
    first = lab.drive(model, lab.load_profiles()["US06"], "US06", -20.0)
    assert first.share_delivered == pytest.approx(0.87, abs=0.005)


def test_regen_limits_are_the_largest_charge_currents_of_the_tests() -> None:
    for folder, ambient in catalog.AMBIENT_C.items():
        largest = max(
            read_mat(c.path).current_a.max() for c in catalog.drive_cycles() if c.folder == folder
        )
        assert largest == pytest.approx(lab.regen_limit_a(ambient), rel=0.08), folder


def test_cold_tests_warm_the_cell_by_about_2_to_5_degrees() -> None:
    rises = [
        np.ptp(read_mat(c.path).temperature_c)
        for c in catalog.drive_cycles()
        if c.folder == "n20degC"
    ]
    assert 1.5 < min(rises) < 2.5
    assert 5.0 < max(rises) < 6.0


def test_unidentifiable_levels_are_the_lowest_at_10_25_and_40() -> None:
    dropped = {}
    for entry in read()["temperatures"]:
        levels = entry["variants"]["charge_transfer"]["levels"]
        bad = [lv for lv in levels if not lv["identifiable"]]
        if bad:
            assert bad == [levels[-1]]
            dropped[entry["folder"]] = bad[0]["tau2_s"]
    assert set(dropped) == {"10degC", "25degC", "40degC"}
    assert min(dropped.values()) > 630
    assert max(dropped.values()) < 940


def test_windows_of_the_real_tests() -> None:
    for folder in catalog.AMBIENT_C:
        h = _hppc(folder)
        points = ocv.rest_points(h)
        ranges = identify.windows(h, points)
        levels = read()["temperatures"][list(catalog.AMBIENT_C).index(folder)]
        assert len(ranges) == len(levels["variants"]["linear"]["levels"])

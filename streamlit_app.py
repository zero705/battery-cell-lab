"""Battery Cell Lab: an equivalent circuit model of the LG 18650HG2 cell, in the browser.

Run with: streamlit run streamlit_app.py
"""

from __future__ import annotations

import gzip
import io
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from celllab import lab  # noqa: E402
from celllab.ecm import (  # noqa: E402
    FARADAY,
    GAS_CONSTANT,
    KELVIN,
    CellModel,
    simulate_current,
)
from celllab.model_file import load_model, read  # noqa: E402

DATA = ROOT / "data"
REPOSITORY = "https://github.com/zero705/battery-cell-lab"
DATASET_DOI = "https://doi.org/10.17632/b5mj79w5w9.2"
SAFE_URL = re.compile(r"https://[\w.-]+(?:/[\w./?=&%~+-]*)?")
TEMPERATURES = (-20.0, -10.0, 0.0, 10.0, 25.0, 40.0)
CYCLES = ("UDDS", "HWFET", "LA92", "US06")
CYCLE_LABELS = {
    "UDDS": "UDDS (city)",
    "HWFET": "HWFET (highway)",
    "LA92": "LA92 (aggressive city)",
    "US06": "US06 (fast, hard acceleration)",
}
# One hue per temperature, cold blue to warm red; the order follows the temperature.
TEMPERATURE_COLOURS = ["#1f4e9c", "#3a7bd5", "#6ca8e8", "#e3a33b", "#d96a2b", "#a8321d"]
PARTS = {
    "ocv_v": "Open-circuit voltage",
    "ohmic_v": "Ohmic (R0)",
    "charge_transfer_v": "Charge transfer (Butler-Volmer)",
    "rc1_v": "Fast RC (tau1)",
    "rc2_v": "Slow RC (tau2)",
}
CHART_HEIGHT = 320
NOMINAL_AH = 3.0  # the cell's nominal capacity (the dataset's technical report); 1C = 3 A
PULSE_A = 0.3  # a current above this, either way, is a pulse (as in celllab.identify)
SERIES = "Series"  # the column that tells lines apart (an empty name draws no chart at all)
MEASURED_COLOUR, MODEL_COLOUR = "#1d232a", "#d96a2b"  # as in the README figures


def https_link(label: str, url: str) -> str:
    """A Markdown link, only to a plain https URL (nothing else is rendered as a link)."""
    if not SAFE_URL.fullmatch(url):
        raise ValueError(f"not a plain https URL: {url!r}")
    return f"[{label}]({url})"


def temperature_label(t_c: float) -> str:
    return f"{t_c:g} °C"


@st.cache_resource(show_spinner=False)
def get_model() -> CellModel:
    return load_model()


# The widgets only offer these values, but a browser can send anything, so every value that
# reaches a computation or a file name is checked again on the server.
LAB_TEMPERATURES_C = range(-20, 41, 5)
LAB_START_SOC_PERCENT = range(20, 101, 5)


def checked_drive_inputs(cycle: str, temperature_c: float, start_soc: float) -> None:
    if cycle not in CYCLES:
        raise ValueError(f"unknown drive cycle: {cycle!r}")
    if temperature_c not in LAB_TEMPERATURES_C:
        raise ValueError(f"temperature out of range: {temperature_c!r}")
    if round(start_soc * 100) not in LAB_START_SOC_PERCENT:
        raise ValueError(f"start state of charge out of range: {start_soc!r}")


def checked_test(folder: str, kind: str) -> None:
    known = {(r["folder"], r["kind"]) for r in json_validation()["variants"]["charge_transfer"]}
    if (folder, kind) not in known:
        raise ValueError(f"unknown test: {folder!r}, {kind!r}")


@st.cache_data(show_spinner=False)
def get_model_data() -> dict[str, Any]:
    return read()


@st.cache_resource(show_spinner=False)
def json_validation() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / "validation.json").read_text(encoding="utf-8"))
    return data


@st.cache_data(show_spinner=False)
def get_validation() -> pd.DataFrame:
    frames = []
    for variant, rows in json_validation()["variants"].items():
        frame = pd.DataFrame(rows)
        frame["variant"] = variant
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


# Bounded caches: the inputs are few, but memory on a free host is not.
@st.cache_data(show_spinner=False, max_entries=16)
def get_trace(folder: str, kind: str) -> pd.DataFrame:
    checked_test(folder, kind)
    raw = gzip.decompress((DATA / "traces" / f"{folder}_{kind}.csv.gz").read_bytes())
    return pd.read_csv(io.BytesIO(raw))


@st.cache_data(show_spinner=False)
def get_pulses() -> pd.DataFrame:
    return pd.read_csv(DATA / "pulses.csv", comment="#")


@st.cache_data(show_spinner=False)
def get_profiles() -> dict[str, np.ndarray]:
    return lab.load_profiles()


@st.cache_data(show_spinner=False, max_entries=64)
def run_drive(
    cycle: str, temperature_c: float, start_soc: float
) -> tuple[dict[str, float], pd.DataFrame]:
    """Run one drive in the lab: its summary, and a trace every 5 s (empty if the cell cannot
    start the drive)."""
    checked_drive_inputs(cycle, temperature_c, start_soc)
    model = get_model()
    capacity = reference_capacity_ah()
    result = lab.drive(
        model, get_profiles()[cycle], cycle, temperature_c, (1 - start_soc) * capacity
    )
    s = result.simulation
    step = 5
    trace = pd.DataFrame(
        {
            "hours": s.time_s[::step] / 3600,
            "Voltage (V)": s.voltage_v[::step],
            "Current (A)": s.current_a[::step],
            "State of charge (%)": 100 * (1 - s.charge_ah[::step] / capacity),
            "Heat (W)": s.heat_w[::step],
        }
    )
    summary = {
        "energy_wh": result.energy_wh,
        "charge_ah": result.charge_ah,
        "heat_wh": result.heat_wh,
        "duration_h": result.duration_h,
        "cycles": result.cycles_completed,
        "share": result.share_delivered,
    }
    return summary, trace


def reference_capacity_ah() -> float:
    """Where the 25 degC open-circuit voltage curve ends: the charge of the 25 degC C/20
    discharge to 2.8 V, on the curve's 5 mAh grid (2.775 Ah)."""
    data = get_model_data()
    for entry in data["temperatures"]:
        if entry["ambient_c"] == 25.0:
            return float(entry["ocv"]["charge_ah"][-1])
    raise LookupError("no 25 degC table")


def line_chart(frame: pd.DataFrame, x: str, y: str, colour: str | None, title: str) -> alt.Chart:
    """A line chart; every field must be a column of the frame with a non-empty name, since
    Vega-Lite silently draws nothing for an empty field name."""
    for field in (x, y, colour):
        if field is not None and (not field or field not in frame.columns):
            raise ValueError(f"not a named column of the frame: {field!r}")
    tooltip: list[Any] = [
        alt.Tooltip(f"{x}:Q", format=".3g"),
        alt.Tooltip(f"{y}:Q", format=".4g"),
    ]
    encoding: dict[str, Any] = {
        "x": alt.X(f"{x}:Q", title=x),
        "y": alt.Y(f"{y}:Q", title=y, scale=alt.Scale(zero=False)),
    }
    if colour is not None:
        names = sorted(frame[colour].unique())
        scale = (
            alt.Scale(domain=["Measured", "Model"], range=[MEASURED_COLOUR, MODEL_COLOUR])
            if names == ["Measured", "Model"]
            else alt.Undefined
        )
        encoding["color"] = alt.Color(
            f"{colour}:N", title=None, scale=scale, legend=alt.Legend(orient="bottom")
        )
        tooltip.append(alt.Tooltip(f"{colour}:N"))
    chart: alt.Chart = (
        alt.Chart(frame, title=title, height=CHART_HEIGHT)
        .mark_line(strokeWidth=1.5)
        .encode(tooltip=tooltip, **encoding)
        .interactive(bind_y=False)
    )
    return chart


def validation_tests() -> int:
    """How many drive-cycle tests the model was checked on."""
    return len(json_validation()["variants"]["charge_transfer"])


def sidebar() -> None:
    st.sidebar.header("Battery Cell Lab")
    st.sidebar.markdown(
        "A model of one LG 18650HG2 lithium-ion cell (3 Ah, NMC / graphite + SiO), identified "
        f"from McMaster University's laboratory tests and checked on {validation_tests()} "
        "drive-cycle tests from -20 to 40 °C."
    )
    st.sidebar.markdown(
        https_link("Source code and method", REPOSITORY)
        + " · "
        + https_link("Test data", DATASET_DOI)
    )


def tab_response() -> None:
    st.markdown(
        "When a current starts, the voltage of a cell drops at once, then keeps sinking; when "
        "the current stops, it jumps back part of the way and then creeps back over minutes. "
        "The model explains this with a small circuit: the **open-circuit voltage**, an "
        "**ohmic** resistance (the instant step), a **charge-transfer** term that grows less "
        "than in proportion to the current, and two **RC pairs**, a fast one and a slow one."
    )
    t_c = st.select_slider(
        "Chamber temperature",
        options=TEMPERATURES,
        value=25.0,
        format_func=temperature_label,
        key="pulse_temperature",
    )
    if t_c not in TEMPERATURES:
        raise ValueError(f"unknown temperature: {t_c!r}")
    pulses = get_pulses()
    p = pulses[pulses["ambient_c"] == t_c].reset_index(drop=True)
    # The level of each pulse: the median while it flows (the first sample can overshoot).
    discharge = float(-p["current_a"][p["current_a"] < -PULSE_A].median())
    charge = float(p["current_a"][p["current_a"] > PULSE_A].median())
    st.markdown(
        f"Below, from the HPPC test at {temperature_label(t_c)}: a real {discharge:.2g} A "
        f"discharge pulse ({discharge / NOMINAL_AH:.2g}C) for 10 s, 40 s of rest, a "
        f"{charge:.2g} A charge pulse and the rest after it, at about half charge."
    )
    sim = simulate_current(
        get_model(),
        p["time_s"].to_numpy(),
        p["current_a"].to_numpy(),
        p["temperature_c"].to_numpy(),
        float(p["charge_ah"].iloc[0]),
    )
    frame = pd.concat(
        [
            pd.DataFrame(
                {"Time (s)": p["time_s"], "Voltage (V)": p["voltage_v"], SERIES: "Measured"}
            ),
            pd.DataFrame({"Time (s)": p["time_s"], "Voltage (V)": sim.voltage_v, SERIES: "Model"}),
        ]
    )
    st.altair_chart(
        line_chart(frame, "Time (s)", "Voltage (V)", SERIES, "Terminal voltage"),
        width="stretch",
    )
    parts = pd.concat(
        [
            pd.DataFrame(
                {"Time (s)": p["time_s"], "Voltage (mV)": 1e3 * getattr(sim, name), SERIES: label}
            )
            for name, label in PARTS.items()
            if name != "ocv_v"
        ]
    )
    st.altair_chart(
        line_chart(parts, "Time (s)", "Voltage (mV)", SERIES, "What each part of the circuit adds"),
        width="stretch",
    )
    error = 1e3 * (sim.voltage_v - p["voltage_v"].to_numpy())
    st.caption(
        f"Over this excerpt the model is {np.sqrt(np.mean(error**2)):.1f} mV RMS from the "
        "measurement. The pulse is part of the test the parameters were identified from."
    )


def tab_circuit() -> None:
    st.markdown(
        "Each parameter was fitted at every state of charge of the HPPC test, at each of six "
        "temperatures. Between them the model interpolates: linearly in the charge removed, and "
        "in temperature along the Arrhenius law (the logarithm of each value linear in 1/T)."
    )
    data = get_model_data()
    rows = []
    levels = dropped = 0
    for entry in data["temperatures"]:
        for level in entry["variants"]["charge_transfer"]["levels"]:
            levels += 1
            if not level["identifiable"]:
                dropped += 1
                continue
            rows.append(
                {
                    "Temperature": temperature_label(entry["ambient_c"]),
                    "Charge removed (Ah)": level["charge_ah"],
                    "R0 (mOhm)": 1e3 * level["r0_ohm"],
                    "R1 (mOhm)": 1e3 * level["r1_ohm"],
                    "tau1 (s)": level["tau1_s"],
                    "R2 (mOhm)": 1e3 * level["r2_ohm"],
                    "tau2 (s)": level["tau2_s"],
                    "Charge-transfer resistance at small current (mOhm)": 1e3
                    * GAS_CONSTANT
                    * (level["temperature_c"] + KELVIN)
                    / (FARADAY * level["i0_a"]),
                    "Fit error over the window (mV RMS)": 1e3 * level["rms_v"],
                }
            )
    frame = pd.DataFrame(rows)
    quantity = st.selectbox("Quantity", list(frame.columns[2:]), key="circuit_quantity")
    order = [temperature_label(t) for t in TEMPERATURES]
    chart = (
        alt.Chart(frame, height=CHART_HEIGHT)
        .mark_line(point=True, strokeWidth=1.5)
        .encode(
            x=alt.X("Charge removed (Ah):Q"),
            y=alt.Y(f"{quantity}:Q", scale=alt.Scale(type="log")),
            color=alt.Color(
                "Temperature:N",
                sort=order,
                scale=alt.Scale(domain=order, range=TEMPERATURE_COLOURS),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                "Temperature",
                alt.Tooltip("Charge removed (Ah):Q", format=".2f"),
                alt.Tooltip(f"{quantity}:Q", format=".3g"),
            ],
        )
    )
    st.altair_chart(chart, width="stretch")
    ocv = pd.concat(
        [
            pd.DataFrame(
                {
                    "Charge removed (Ah)": entry["ocv"]["charge_ah"],
                    "Open-circuit voltage (V)": entry["ocv"]["voltage_v"],
                    "Temperature": temperature_label(entry["ambient_c"]),
                }
            )
            for entry in data["temperatures"]
        ]
    )
    chart = (
        alt.Chart(ocv, title="Open-circuit voltage", height=CHART_HEIGHT)
        .mark_line(strokeWidth=1.5)
        .encode(
            x="Charge removed (Ah):Q",
            y=alt.Y("Open-circuit voltage (V):Q", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "Temperature:N",
                sort=order,
                scale=alt.Scale(domain=order, range=TEMPERATURE_COLOURS),
                legend=alt.Legend(orient="bottom"),
            ),
        )
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "The open-circuit voltage takes the shape of the C/20 discharge and passes through the "
        "voltages at the end of the hour-long rests of the HPPC test. Levels whose slow time "
        "constant is longer than any rest in their window cannot be identified and are left "
        f"out ({dropped} of {levels})."
    )


def current_limits(t_c: float) -> str:
    """The tests' current limits at a temperature, in words."""
    discharge, charge = lab.discharge_limit_a(t_c), lab.regen_limit_a(t_c)
    if math.isinf(discharge):
        return (
            f"the charging current of regenerative braking is limited to {charge:g} A; the "
            "discharge current is not limited"
        )
    return (
        f"the discharge current is limited to {discharge:g} A and the charging current of "
        f"regenerative braking to {charge:g} A"
    )


def tab_lab() -> None:
    st.markdown(
        "Drive the cell with a car's power demand, the way the laboratory did: the same power "
        "profile, computed for one cell of a compact electric car, over and over. The tester "
        "limited the current in the cold and never let the voltage fall below 2.8 V; when the "
        "cell cannot give the power within these limits, it gives what it can. The drive ends "
        f"with the first cycle in which it gives less than {lab.MIN_SHARE:.0%} of the energy the "
        "cycle asks for."
    )
    c1, c2, c3 = st.columns(3)
    cycle = c1.selectbox(
        "Drive cycle", CYCLES, format_func=CYCLE_LABELS.__getitem__, key="lab_cycle"
    )
    t_c = c2.slider("Cell temperature (°C)", -20, 40, 25, 5, key="lab_temperature")
    soc = c3.slider("Start state of charge (%)", 20, 100, 100, 5, key="lab_soc")
    summary, trace = run_drive(cycle, float(t_c), soc / 100)
    if trace.empty:
        st.info(
            f"From {soc} % at {t_c} °C the cell cannot start this drive without falling below "
            "2.8 V. Choose a higher state of charge or a warmer cell."
        )
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Energy delivered", f"{summary['energy_wh']:.2f} Wh", border=True)
    m2.metric("Driving time", f"{summary['duration_h']:.2f} h", border=True)
    m3.metric("Cycles completed", f"{summary['cycles']:.1f}", border=True)
    m4.metric("Lost as heat", f"{summary['heat_wh']:.2f} Wh", border=True)
    y = st.radio("Show", list(trace.columns[1:]), horizontal=True, key="lab_show")
    st.altair_chart(line_chart(trace, "hours", y, None, y), width="stretch")
    st.caption(
        f"The cell is held at {t_c} °C and gave {summary['share']:.1%} of the discharge "
        f"energy demanded. As in the tests at this temperature, {current_limits(float(t_c))}. "
        "State of charge is counted against the 25 °C capacity. The trace is shown every 5 s; "
        "the model runs every second."
    )


US06_COLD_SHARE_MEASURED = 0.82  # tests/test_raw_data.py recomputes it from the raw data


def tab_cold() -> None:
    modelled = run_drive("US06", -20.0, 1.0)[0]["share"]
    st.markdown(
        "The same drive at six temperatures. In the cold the cell's resistance rises, so the "
        "voltage sags further under the same power, the current must rise to make up for it, "
        "and the 2.8 V limit comes sooner: the cell gives less of its energy, and more of it "
        "turns into heat. The tests also limited the current in the cold. On US06 at -20 °C "
        "the cell falls behind from the first cycle: in the laboratory test it delivered "
        f"{US06_COLD_SHARE_MEASURED:.0%} of the discharge energy the first cycle asked for, and "
        f"the model gives {modelled:.0%}. At 40 °C the cell gives a little less than at 25 °C on "
        "three of the cycles, as in the data, where it gave less charge at 40 °C."
    )
    cycle = st.selectbox(
        "Drive cycle", CYCLES, format_func=CYCLE_LABELS.__getitem__, key="cold_cycle"
    )
    rows = []
    for t_c in TEMPERATURES:
        summary, _ = run_drive(cycle, t_c, 1.0)
        rows.append(
            {
                "Temperature": temperature_label(t_c),
                "Energy delivered (Wh)": summary["energy_wh"],
                "Lost as heat (Wh)": summary["heat_wh"],
                "Driving time (h)": summary["duration_h"],
                "Energy demanded that was delivered": summary["share"],
            }
        )
    frame = pd.DataFrame(rows)
    order = [temperature_label(t) for t in TEMPERATURES]
    chart = (
        alt.Chart(frame, height=CHART_HEIGHT)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("Temperature:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Energy delivered (Wh):Q"),
            color=alt.Color(
                "Temperature:N",
                sort=order,
                legend=None,
                scale=alt.Scale(domain=order, range=TEMPERATURE_COLOURS),
            ),
            tooltip=[
                "Temperature",
                alt.Tooltip("Energy delivered (Wh):Q", format=".2f"),
                alt.Tooltip("Lost as heat (Wh):Q", format=".2f"),
            ],
        )
    )
    st.altair_chart(chart, width="stretch")
    shown = frame.style.format(precision=2).format(
        "{:.0%}", subset=["Energy demanded that was delivered"]
    )
    st.dataframe(shown, hide_index=True, width="stretch")
    st.caption(
        "The model holds the cell at the chosen temperature; a real cell warms up as it works, "
        "by about 2 to 5 °C in the -20 °C tests. The model's error is largest in the cold "
        "(see Validation)."
    )


def tab_validation() -> None:
    frame = get_validation()
    st.markdown(
        "The model was given the measured current and cell temperature of every usable "
        "drive-cycle test and predicted the voltage; none of these tests was used to identify it. "
        "Mixed1-4 served to compare modelling choices (development set); the other tests "
        "were run once, with the final model (test set)."
    )
    main = frame[frame["variant"] == "charge_transfer"]
    summary = (
        main.groupby(["ambient_c", "split"])["rms_mv"]
        .median()
        .unstack()
        .rename(index=temperature_label, columns=lambda s: f"Median error, {s} set")
        .rename_axis(index="Chamber temperature", columns=None)
    )
    st.dataframe(summary.style.format("{:.1f} mV"), width="stretch")
    folder = st.selectbox(
        "Temperature",
        main["folder"].unique().tolist(),
        format_func=lambda f: temperature_label(
            float(main[main["folder"] == f]["ambient_c"].iloc[0])
        ),
        key="val_folder",
    )
    kinds = main[main["folder"] == folder]["kind"].tolist()
    kind = st.selectbox("Test", kinds, key="val_kind")
    trace = get_trace(folder, kind)
    ambient = float(main[main["folder"] == folder]["ambient_c"].iloc[0])
    long = pd.concat(
        [
            pd.DataFrame(
                {
                    "hours": trace["time_s"] / 3600,
                    "Voltage (V)": trace["measured_v"],
                    SERIES: "Measured",
                }
            ),
            pd.DataFrame(
                {
                    "hours": trace["time_s"] / 3600,
                    "Voltage (V)": trace["charge_transfer_v"],
                    SERIES: "Model",
                }
            ),
        ]
    )
    st.altair_chart(
        line_chart(
            long,
            "hours",
            "Voltage (V)",
            SERIES,
            f"{kind} at {temperature_label(ambient)}",
        ),
        width="stretch",
    )
    row = main[(main["folder"] == folder) & (main["kind"] == kind)].iloc[0]
    st.caption(
        f"Error: {row['rms_mv']:.1f} mV RMS, {row['p95_abs_mv']:.0f} mV at the 95th "
        f"percentile, {row['max_abs_mv']:.0f} mV at most. Trace shown every 2 s."
    )
    with st.expander("Every test"):
        table = main[["ambient_c", "kind", "split", "rms_mv", "p95_abs_mv", "max_abs_mv"]].rename(
            columns={
                "ambient_c": "°C",
                "kind": "Test",
                "split": "Set",
                "rms_mv": "RMS (mV)",
                "p95_abs_mv": "95th pct (mV)",
                "max_abs_mv": "Max (mV)",
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")


def tab_method() -> None:
    st.markdown(
        f"""
**Data.** P. Kollmeyer, M. Naguib, M. Skells, *LG 18650HG2 Li-ion Battery Data*, McMaster
University, Mendeley Data, version 2, 2020, {https_link("doi:10.17632/b5mj79w5w9.2", DATASET_DOI)},
licence CC BY 4.0. A new 3 Ah cell in a thermal chamber, on a Digatron cycler (voltage and
current within 0.1 % of full scale); HPPC, C/20 and drive-cycle tests at -20, -10, 0, 10, 25
and 40 °C. Every file is checked against the SHA-256 that Mendeley publishes.

**Model.** Open-circuit voltage + ohmic resistance + Butler-Volmer charge transfer + two RC
pairs, all functions of the charge removed and the temperature.

**Identification.** Open-circuit voltage from the C/20 discharge, moved onto the HPPC rest
voltages. Circuit parameters fitted to every state of charge of the HPPC test by variable
projection with non-negative least squares, from several starting points.

**Validation.** {validation_tests()} drive-cycle tests the identification never saw, with
measured current and temperature as inputs; {len(json_validation()["excluded"])} tests of the
dataset are unusable and are listed in the repository with the reason.

The full account: {https_link("README and docs", REPOSITORY)}.
"""
    )


def main() -> None:
    st.set_page_config(page_title="Battery Cell Lab", layout="wide")
    sidebar()
    st.title("Battery Cell Lab", anchor=False)
    st.caption(
        "An equivalent circuit model of the LG 18650HG2 lithium-ion cell, identified from "
        "laboratory tests and validated on drive cycles from -20 to 40 °C."
    )
    tabs = st.tabs(
        [
            "How a cell responds",
            "The circuit",
            "Virtual lab",
            "Cold weather",
            "Validation",
            "Method",
        ]
    )
    with tabs[0]:
        tab_response()
    with tabs[1]:
        tab_circuit()
    with tabs[2]:
        tab_lab()
    with tabs[3]:
        tab_cold()
    with tabs[4]:
        tab_validation()
    with tabs[5]:
        tab_method()


if __name__ == "__main__":
    main()

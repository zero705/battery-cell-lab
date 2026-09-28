"""The Streamlit app runs, and every tab shows what it should."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import streamlit_app

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def test_app_runs_without_errors(app: AppTest) -> None:
    assert app.title[0].value == "Battery Cell Lab"
    assert len(app.tabs) == 6


def test_lab_shows_the_energy_of_a_drive(app: AppTest) -> None:
    labels = [m.label for m in app.metric]
    assert labels == ["Energy delivered", "Driving time", "Cycles completed", "Lost as heat"]
    assert app.metric[0].value.endswith(" Wh")


@pytest.mark.parametrize("temperature", [-20, 40])
def test_lab_runs_at_the_ends_of_the_range(app: AppTest, temperature: int) -> None:
    app.slider(key="lab_temperature").set_value(temperature).run()
    assert not app.exception


def test_every_pulse_temperature_runs(app: AppTest) -> None:
    for value in streamlit_app.TEMPERATURES:
        app.select_slider(key="pulse_temperature").set_value(value).run()
        assert not app.exception


def test_every_validation_test_can_be_shown(app: AppTest) -> None:
    folders = app.selectbox(key="val_folder").options
    assert len(folders) == 6
    app.selectbox(key="val_folder").set_value("n20degC").run()
    assert not app.exception
    assert len(app.selectbox(key="val_kind").options) == 12


def test_circuit_quantities_can_be_chosen(app: AppTest) -> None:
    for option in app.selectbox(key="circuit_quantity").options:
        app.selectbox(key="circuit_quantity").set_value(option).run()
        assert not app.exception


def test_every_chart_names_its_fields(app: AppTest) -> None:
    """Vega-Lite draws nothing, and reports nothing, for a field with an empty name."""
    charts = app.get("vega_lite_chart")
    assert len(charts) == 7  # two pulse charts, parameter, OCV, lab, cold weather, validation
    for chart in charts:
        spec = json.loads(chart.proto.spec)
        fields = re.findall(r'"field":\s*"([^"]*)"', json.dumps(spec))
        assert fields
        assert all(fields), spec.get("title")


def test_line_chart_refuses_a_missing_or_empty_field() -> None:
    frame = pd.DataFrame({"x": [0.0, 1.0], "y": [1.0, 2.0], "": ["a", "b"]})
    streamlit_app.line_chart(frame, "x", "y", None, "fine")
    for colour in ("", "missing"):
        with pytest.raises(ValueError, match="named column"):
            streamlit_app.line_chart(frame, "x", "y", colour, "broken")


@pytest.mark.parametrize(
    ("cycle", "temperature", "soc"),
    [
        ("UDDS", 25.0, 1.01),
        ("UDDS", 25.0, 0.15),
        ("UDDS", 45.0, 1.0),
        ("UDDS", 22.5, 1.0),
        ("Mixed1", 25.0, 1.0),
        ("../x", 25.0, 1.0),
    ],
)
def test_lab_inputs_are_checked_on_the_server(cycle: str, temperature: float, soc: float) -> None:
    with pytest.raises(ValueError, match=r"unknown|out of range"):
        streamlit_app.checked_drive_inputs(cycle, temperature, soc)


def test_lab_inputs_the_widgets_offer_are_accepted() -> None:
    for t_c in range(-20, 41, 5):
        for soc in range(20, 101, 5):
            streamlit_app.checked_drive_inputs("US06", float(t_c), soc / 100)


@pytest.mark.parametrize(
    ("folder", "kind"),
    [("25degC", "HWFET"), ("..", "x"), ("25degC/../../x", "UDDS"), ("n20degC", "UDDS\x00")],
)
def test_only_known_traces_are_read(folder: str, kind: str) -> None:
    with pytest.raises(ValueError, match="unknown test"):
        streamlit_app.get_trace(folder, kind)


def test_a_drive_that_cannot_start_shows_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(streamlit_app, "run_drive", lambda *a: ({}, pd.DataFrame()))
    monkeypatch.setattr(st, "info", shown.append)
    streamlit_app.tab_lab()
    assert shown
    assert "cannot start this drive" in shown[0]


def test_https_link_refuses_anything_but_plain_https() -> None:
    assert streamlit_app.https_link("a", "https://example.org/x") == "[a](https://example.org/x)"
    for bad in (
        "http://example.org",
        "javascript:alert(1)",
        "https://x.org/a b",
        "https://x.org/)",
    ):
        with pytest.raises(ValueError, match="plain https"):
            streamlit_app.https_link("a", bad)


def test_temperature_label() -> None:
    assert streamlit_app.temperature_label(-20.0) == "-20 °C"
    assert streamlit_app.temperature_label(25.0) == "25 °C"

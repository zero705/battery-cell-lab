"""The inventory of the dataset's tests."""

from __future__ import annotations

import json

import pytest

from celllab import catalog


def test_manifest_lists_every_file_with_a_fingerprint() -> None:
    manifest = json.loads(catalog.MANIFEST.read_text(encoding="utf-8"))
    assert manifest["licence"]["name"] == "Creative Commons Attribution 4.0 International"
    assert manifest["doi"] == "https://doi.org/10.17632/b5mj79w5w9.2"
    files = manifest["files"]
    assert len(files) == 206
    assert {f["folder"] for f in files} == set(catalog.AMBIENT_C)
    for f in files:
        assert len(f["sha256"]) == 64
        assert f["url"].startswith("https://data.mendeley.com/")
        assert f["filename"].endswith(".mat")


def test_every_temperature_has_one_hppc_and_one_c20_test() -> None:
    for folder in catalog.AMBIENT_C:
        assert catalog.find(folder, "HPPC").kind == "HPPC"
        assert catalog.find(folder, "C20DisCh").ambient_c == catalog.AMBIENT_C[folder]


def test_unknown_test_is_not_found() -> None:
    with pytest.raises(LookupError, match="0 files"):
        catalog.find("25degC", "Mixed9")


def test_drive_cycles_leave_out_the_excluded_tests() -> None:
    cycles = catalog.drive_cycles()
    assert len(cycles) == 62
    assert len(catalog.EXCLUDED) == 8
    assert not any((c.folder, c.kind) in catalog.EXCLUDED for c in cycles)
    counted = {folder: sum(c.folder == folder for c in cycles) for folder in catalog.AMBIENT_C}
    # 12 cycles per temperature, less the excluded ones and those the dataset does not have
    # (Mixed3 at 0 and 10 degC).
    assert counted == {
        "n20degC": 12,
        "n10degC": 11,
        "0degC": 11,
        "10degC": 10,
        "25degC": 11,
        "40degC": 7,
    }
    temps = [c.ambient_c for c in cycles]
    assert temps == sorted(temps)

# Changelog

## [Unreleased]

- A link to the live app in the README.
- The app sets the sidebar text colour, so Streamlit 1.65 no longer prints a warning in the
  browser console.
- The download tool tries again when Mendeley fails for a moment, and CI keeps the raw data
  between runs instead of downloading it on every push.
- The app runs on Streamlit 1.66.1. It allows Pillow 13, which fixes the known security issues
  of Pillow 12.3.0 (the app opens no image files, but it shouldn't ship them anyway).

## [0.1.0] - 2026-10-20

First release.

- Download of the McMaster LG 18650HG2 data (206 files), with every file checked against the
  SHA-256 that Mendeley Data publishes, and an audit of all of them. Eight unusable drive-cycle
  tests are left out, each with its reason.
- Open-circuit voltage from the C/20 discharge, moved onto the HPPC rest voltages.
- Equivalent circuit model with a Butler-Volmer term and two RC pairs, fitted at every state of
  charge of the HPPC test at six temperatures.
- Validation on 62 drive-cycle tests from -20 to 40 °C, with a development set and a test set,
  for the model with and without the charge-transfer term.
- A virtual lab that drives the model with the tests' power profiles and current limits.
- A Streamlit app with six tabs.
- Tests for the model, the app and every number in the docs (100 % coverage), CI on Linux and
  Windows with Python 3.10 to 3.14, a dependency audit and CodeQL.

[Unreleased]: https://github.com/zero705/battery-cell-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zero705/battery-cell-lab/releases/tag/v0.1.0

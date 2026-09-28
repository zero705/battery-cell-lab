# Battery Cell Lab

[![CI](https://github.com/zero705/battery-cell-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/zero705/battery-cell-lab/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![Typed](https://img.shields.io/badge/mypy-strict-blue)

An equivalent circuit model of a lithium-ion cell, the **LG 18650HG2** (3 Ah, NMC / graphite +
SiO), identified from McMaster University's laboratory tests of a new cell and checked against
**63 drive-cycle tests from -20 to 40 °C** that the identification never saw. Given a current
and a temperature, it predicts the terminal voltage, how much charge is left and how much heat
the cell gives off; given a car's power demand, it tells how much energy the cell delivers
before it can no longer keep up. A Streamlit app shows it all, from a single current pulse to a
drive in the cold.

![Measured and modelled voltage of two drive-cycle tests, LA92 at 25 °C and UDDS at -20 °C, with the error below each; the model follows the measurement closely at 25 °C and runs up to about 100 mV high during braking at -20 °C.](docs/images/validation.png)

*Measured voltage and the model's prediction from the measured current and cell temperature, on
two tests the model was not fitted to. Drawn by `tools/make_figures.py`.*

## Results

The model predicts the voltage of the drive-cycle tests to a median of **29 mV RMS**, under 1 %
of the cell voltage. The tests were split before the modelling choices were compared: choices were
compared on the Mixed1-4 cycles (development set) only, and the other 42 tests (test set) were run
once, with the final model.

<!-- generated: results -->
| Chamber temperature | Tests | Median error, development set | Median error, test set | Worst test | Median error, two RC pairs only |
|---|---|---|---|---|---|
| -20 °C | 12 | 63.6 mV | 60.0 mV | 87.2 mV | 69.7 mV |
| -10 °C | 12 | 49.0 mV | 42.8 mV | 74.6 mV | 47.1 mV |
| 0 °C | 11 | 26.6 mV | 26.1 mV | 50.7 mV | 25.5 mV |
| 10 °C | 10 | 29.3 mV | 23.8 mV | 51.9 mV | 26.1 mV |
| 25 °C | 11 | 27.9 mV | 20.7 mV | 55.8 mV | 26.9 mV |
| 40 °C | 7 | 18.0 mV | 15.4 mV | 31.1 mV | 16.6 mV |
| **All** | **63** | **30.3 mV** | **28.6 mV** | **87.2 mV** | **29.3 mV** |
<!-- end generated -->

Each error is the RMS over a whole test, from full to the end of the test and the rest after it,
sampled every 0.1 s. The last column is the textbook circuit without the charge-transfer term:
the term changes little from 0 °C up, and in the cold it lowers the median and cuts the worst
test at -20 °C from 135 to 87 mV. [Every test](docs/method.md#6-every-test) is listed in the
method.

![RMS error of every drive-cycle test by temperature, with and without the charge-transfer term.](docs/images/error_by_temperature.png)

**Where the error comes from.** From 0 to 40 °C the largest errors sit at the end of discharge,
where the voltage falls steeply. In the cold, most of the error comes from regenerative braking:
in each of the twelve -20 °C tests the model's voltage runs 82 to 104 mV high on average while
the cell charges, while during discharge its mean error stays within 17 mV in eleven of them
(US06: 58 mV low). The HPPC test charges the cold cell only with small pulses (0.3 to 1.5 A), and
the model's charge-transfer term is symmetric, so charging in the cold is its weakest part.

### Checks that do not depend on the model

- **The pulse resistances match the dataset authors' own figures.** Their report gives the
  10-second discharge resistance at half charge; read from the same raw pulses here it is
  179.3 / 89.8 / 53.0 / 27.2 / 23.6 mΩ at -20 / -10 / 0 / 25 / 40 °C in the report, and within
  0.5 mΩ of each here (`tests/test_raw_data.py`).
- **The cold limits the power, in the data and in the model.** In the -20 °C US06 test the cell
  delivered 82 % of the discharge power of the first cycle; the model, driven by the same power
  demand at -20 °C, delivers 87 %.
- **Every file is the published one.** All 206 test files are checked against the SHA-256 that
  Mendeley Data publishes, and the five unusable tests are left out for a stated reason
  (`celllab/catalog.py`).

## The app

```bash
git clone https://github.com/zero705/battery-cell-lab.git
cd battery-cell-lab
pip install -e ".[app]"
streamlit run streamlit_app.py
```

![The virtual lab: a UDDS drive at 25 °C from full, with the energy delivered, the driving time, the cycles completed and the heat lost, and the cell voltage over the 4.6-hour drive.](docs/images/app.png)

Six tabs: **How a cell responds** (a real pulse and what each part of the circuit adds to it),
**The circuit** (every identified parameter against charge and temperature), **Virtual lab**
(any cycle, temperature and starting charge), **Cold weather** (the same drive at six
temperatures), **Validation** (every test, measured against modelled) and **Method**.

![Energy one full cell delivers on each drive cycle at six temperatures, from the model.](docs/images/cold_weather.png)

## How it works

1. **Model.** Terminal voltage = open-circuit voltage + ohmic drop R0·i + a Butler-Volmer
   charge-transfer term (2RT/F)·asinh(i/2i0) + two RC pairs, a fast one (seconds) and a slow one
   (minutes). Every parameter depends on the charge removed and the temperature. Between the
   six tested temperatures the parameters follow the Arrhenius law (their logarithm linear in
   1/T).
2. **Open-circuit voltage.** The shape of the C/20 discharge, moved onto the voltages at the
   end of the HPPC test's hour-long rests. Predicting each rest point from the others, this is
   off by 8.9 mV RMS, half the 17.8 mV of a curve through the rest points alone.
3. **Identification.** At every state of charge of the HPPC test (eight pulses, a step and an
   hour of rest), the parameters are fitted to the measured voltage by variable projection:
   the resistances are solved exactly with non-negative least squares for each trial of the time
   constants and i0, from twelve starting points. A level whose slow time constant is longer
   than any rest in its window cannot be identified and is not used (3 of 63).
4. **Validation.** Each drive-cycle test is run with its measured current and cell
   temperature, from rest and full, and the predicted voltage is compared sample by sample.

The equations, the data problems found and how each was handled, and every number of the
validation: [docs/method.md](docs/method.md). The dataset and its audit:
[docs/data.md](docs/data.md).

## Limitations

- **One new cell.** The tests are of one cell early in its life; ageing and cell-to-cell spread
  are not in the data.
- **Charging in the cold** is the weakest part (see above).
- **Temperature is an input.** The model uses the measured case temperature; in the lab and
  cold-weather tabs the cell is held at the chosen temperature, while a real cell warms up as it
  works (by about 2 to 5 °C in the -20 °C tests). No thermal model is included.
- **No hysteresis state.** The open-circuit voltage is the one reached after discharging, which
  suits drives, which mostly discharge.

## Reproducing everything

```bash
pip install -e ".[dev]"
python tools/fetch_dataset.py      # 206 files, 112 MB, each checked against its SHA-256
python tools/audit_dataset.py      # the data problems listed in docs/data.md
python tools/identify_model.py     # data/model.json, a few minutes
python tools/validate_model.py     # data/validation.json, traces and power profiles
python tools/extract_examples.py   # data/pulses.csv for the app
python tools/make_figures.py       # docs/images
python tools/update_docs.py        # the generated tables of README.md and docs/method.md
pytest --cov                       # 100 % coverage; the raw-data checks run once it is downloaded
ruff check . && ruff format --check . && mypy
```

The app and the tests need only the files in `data/`; the raw data is needed to rebuild them.
How the app and the tools are protected, and how to report a security problem:
[SECURITY.md](SECURITY.md).

## Project structure

```
src/celllab/        the model: reading the data, open-circuit voltage, circuit, identification,
                    validation, virtual lab
streamlit_app.py    the app
data/               the dataset manifest, the identified model, the validation results and the
                    traces the app plots
tools/              scripts that download, audit, identify, validate and draw
docs/               method, data and figures
tests/              pytest suite, including the app and every stated number about the raw data
```

## Data licence and citation

The test data: P. Kollmeyer, M. Naguib, M. Skells, *LG 18650HG2 Li-ion Battery Data*, McMaster
University, Mendeley Data, V2, 2020, <https://doi.org/10.17632/b5mj79w5w9.2>, licensed
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0). The files in `data/traces/`,
`data/profiles.csv` and `data/pulses.csv` are derived from it (resampled, cut, or compared with
the model) under the same licence. The raw files are not in this repository;
`tools/fetch_dataset.py` downloads them from Mendeley Data.

## Author

Ömer Faruk Şenol, Hybrid and Electric Vehicles Technology, İnönü University

[GitHub](https://github.com/zero705) ·
[LinkedIn](https://www.linkedin.com/in/%C3%B6mer-faruk-%C5%9Fenol-2778a63b5/)

## License

[MIT](LICENSE)

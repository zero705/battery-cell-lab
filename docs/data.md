# The data

## Source

P. Kollmeyer, M. Naguib, M. Skells, *LG 18650HG2 Li-ion Battery Data*, McMaster University,
Mendeley Data, version 2, published 29 January 2020, <https://doi.org/10.17632/b5mj79w5w9.2>,
licence CC BY 4.0.

From the dataset's readme: a new 3 Ah LG HG2 cell, tested in an 8 cu.ft. thermal chamber on a
75 A, 5 V Digatron cycler channel with a voltage and current accuracy of 0.1 % of full scale;
voltage measured with sense leads welded to the terminals, temperature with an AD592 sensor
(±1 °C) on the middle of the case. At 40, 25, 10, 0, -10 and -20 °C, in that order: an HPPC test,
a C/20 discharge and charge, capacity tests, the UDDS, HWFET, LA92 and US06 cycles and eight
mixed cycles, the drive cycles as a power profile for one cell of a compact electric vehicle,
repeated until 95 % of the 1C capacity at that temperature was discharged; below 10 °C "a
reduced regen current limit is set to prevent premature aging of the cells". After each test
the cell was charged at 1C to 4.2 V (50 mA cut-off) at 22 °C or warmer. The drive cycles are
logged every 0.1 s, charges and rests more slowly. The dataset's technical report gives the
cell as NMC / graphite + SiO, 3.6 V nominal, 3.0 Ah nominal.

## Download and fingerprints

`data/dataset.json` lists the 206 MATLAB files with the SHA-256 that the Mendeley Data API
publishes for each (`tools/make_manifest.py` builds it from the saved API response).
`tools/fetch_dataset.py` downloads them over HTTPS and writes a file only if its fingerprint
matches. The CSV copies in the dataset hold the same data and are not used.

## What the audit found

`tools/audit_dataset.py` reads every file. `tests/test_raw_data.py` recomputes the figures below
that the code relies on.

| Finding | Handling |
|---|---|
| In the 205 readable files, 5,751 rows in 176 files repeat the previous time stamp; 5,683 repeat the values too, the rest differ by at most 0.2 mV and 3 mA | the first row of each repeated time is kept |
| The Ah column is reset in the middle of some tests | the charge is integrated from the current |
| The Wh column does not follow the energy (it reads 3 throughout the 25 °C UDDS test, which moves 9.4 Wh) | not used |
| At -20 °C the C/20 discharge voltage rises by up to 0.34 mV in 51 places | made non-increasing by isotonic regression (no sample moves more than 0.28 mV) |
| The C/20 charge and discharge counts disagree by up to 0.19 Ah, within the cycler's ±75 mA at 0.15 A | only the discharge half is used |
| In the -10 °C Mixed4 test nothing is logged for 416 s, from 387 s into the test, while the cycle runs: across the gap the voltage falls from 4.200 to 3.899 V, and the test ends with 0.10 Ah less removed than the least of the other seven mixed cycles at -10 °C | the test is left out |

Eight drive-cycle tests cannot be used and are left out of the validation
(`celllab/catalog.py`):

| Test | Why |
|---|---|
| HWFET at 25 °C | no current flows: the file is 10 minutes of rest |
| LA92 at 10 °C | time goes backwards in four places and three rows hold no values |
| Mixed4 at -10 °C | nothing is logged for 416 s from 387 s into the test, while the cycle runs: the charge moved then is unknown |
| Mixed4 to Mixed8 at 40 °C | run at 23 to 24 °C, not 40 °C, and stopped after 0.19 Ah |

The dataset has no Mixed3 test at 0 and 10 °C. That leaves 62 drive-cycle tests.

The drive-cycle tests also show how the testers limited the current, which the virtual lab
repeats (`celllab/lab.py`, [method.md, section 7](method.md#7-the-virtual-lab)): discharge to
6 A at -20 °C and 12 A at -10 °C, and the charging current of regenerative braking to 1.5 A at
-20 °C, 3 A at -10 and 0 °C and 6 A from 10 °C. And the cell gave less charge at 40 °C than at
25 °C: its C/20 discharge to 2.8 V removed 2.687 Ah at 40 °C and 2.779 Ah at 25 °C.

## What is in this repository

The raw files are not. `data/` holds the dataset's record and file list, and what the model and
the app need, derived from the raw data by the tools under the dataset's CC BY 4.0 licence:

| File | Contents | Written by |
|---|---|---|
| `mendeley_record.json` | the Mendeley Data API's record of the dataset, saved unchanged | the Mendeley Data API |
| `dataset.json` | the file list with fingerprints and download addresses | `tools/make_manifest.py` |
| `model.json` | open-circuit voltage curves, rest points and circuit parameters | `tools/identify_model.py` |
| `development.json` | the comparisons that chose the model (method.md, section 5) | `tools/compare_variants.py` |
| `validation.json` | the error on every drive-cycle test, both circuits, and where it sits | `tools/validate_model.py` |
| `traces/*.csv.gz` | measured and modelled voltage, current and temperature of each test, every 2 s | `tools/validate_model.py` |
| `profiles.csv` | one period of each cycle's power demand, 1 s steps | `tools/validate_model.py` |
| `pulses.csv` | one pulse pair per temperature at about half charge | `tools/extract_examples.py` |

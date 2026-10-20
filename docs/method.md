# Method

How the model is built from the test data and how it was checked. The dataset and its problems
are in [data.md](data.md). The tables marked as generated are written by `tools/update_docs.py`
from `data/`, and `tests/test_docs.py` fails if they fall out of date; it also checks the other
numbers of this page against `data/`, and `tests/test_raw_data.py` those about the raw data.

## 1. The model

With the current i positive on charge and q the charge removed since the cell was full:

    v = OCV(q, T) + R0 i + eta(i) + u1 + u2
    eta(i) = (2 R T / F) asinh(i / (2 i0))            charge transfer (Butler-Volmer, alpha = 1/2)
    du_k/dt = (R_k i - u_k) / tau_k,   k = 1, 2        two RC pairs

R0 is the ohmic resistance, the instant step of the voltage when the current changes. The
Butler-Volmer term is the overpotential of the reaction at the electrode surfaces: it acts like a
resistance RT/(F i0) at small currents and grows only logarithmically at large ones, which is
why a cold cell's resistance falls as the pulse grows (the dataset's report shows this). The two
RC pairs are the slower polarisation, one over seconds and one over minutes.

The RC pairs are advanced exactly over each sample interval with the current held:
u[n+1] = a u[n] + R (1 - a) i[n], a = exp(-dt/tau), so the result does not depend on the step
length (`tests/test_ecm.py` checks this against the closed-form step response). R = 8.314462618
J/(mol K) and F = 96485.33212 C/mol are the exact SI values to ten significant digits.

The parameters R0, R1, tau1, R2, tau2 and i0 are tables over q at each of the six test
temperatures. Between states of charge they are interpolated linearly in q; between temperatures
their logarithm is interpolated linearly in 1/T, the Arrhenius form of thermally activated
processes. The open-circuit voltage is interpolated linearly in temperature. Outside the tested
range the values are held at the nearest end.

## 2. Open-circuit voltage

Two tests measure it, and neither alone is enough. The HPPC test rests the cell for an hour
after each of its 9 to 11 steps down in state of charge: the voltage at the end of each rest,
and at the start of the test, is the open-circuit voltage after discharging, but only at those
10 to 12 points. The C/20 test discharges the cell at 0.15 A and traces the whole curve, but
under current, below the open-circuit voltage by the cell's polarisation at 0.15 A.

The curve used takes the shape of the C/20 discharge and moves it onto the rest points: the
C/20 voltage plus an offset that passes through every rest point, interpolated between them by a
monotone cubic (PCHIP). To choose the construction, each interior rest point was predicted from
the others (leave one out, 56 points over the six temperatures):

| Construction | RMS error | Largest error |
|---|---|---|
| C/20 shape moved onto the rest points (used) | 8.9 mV | 42 mV |
| Monotone cubic through the rest points alone | 17.8 mV | 40 mV |
| Straight lines between the rest points | 25.6 mV | 70 mV |

The model uses every rest point, so its error between points is smaller than the leave-one-out
figure. The largest error at each temperature is at one of the three lowest states of charge
predicted, near empty, where the curve is steepest.

Only the discharge half of the C/20 test is used. At 0.15 A the cycler's current accuracy
(0.1 % of its 75 A range, ±75 mA) is half the current itself, and the charge counted on the way
down and on the way back up disagrees by up to 0.19 Ah. The HPPC steps, at 0.87 to 0.9 A, count
consistently with the C/20 discharge: at 25 °C, where both end at 2.8 V, they remove 2.776 and
2.779 Ah.

## 3. Identification

At every state of charge the HPPC test runs four pulse pairs, each a 10 s discharge pulse, 40 s
of rest, a 10 s charge pulse and 10 minutes of rest; then a 0.3C discharge to the next state of
charge and an hour of rest. The discharge pulses are 1, 2, 4 and 6C from 0 °C up, 0.5 to 4C at
-10 °C and 0.25 to 2C at -20 °C (1C is 3 A, and 2.9 A at 10 °C); the charge pulses reach 2C from
10 °C up, 1C at 0 and -10 °C and 0.5C at -20 °C. One fit window runs from the end of one
hour-long rest to the end of the next. A window with no charge pulse holds no pulse set and is
dropped; a window whose step discharges the cell to the 2.8 V cut-off ends before that step,
since the cell is far from linear there.

In each window the parameters are fitted by least squares to the measured voltage, sample by
sample. For given tau1, tau2 and i0 the voltage is linear in R0, R1 and R2, so these are solved
exactly with non-negative least squares at every trial (variable projection), and the search runs
over tau1 (0.1-20 s), tau2 (20-2000 s) and i0 (0.005-100 A) only, from twelve starting points,
keeping the best. The window starts from rest, with the RC voltages at zero.

Two choices were made after a first run of the model on all drive cycles (section 5):

- **A straight-line correction to the open-circuit voltage within each window**, fitted with the
  resistances. Without it, an error in the slope of the open-circuit curve inside the window,
  largest near empty, is taken up by the slow RC pair, whose resistance and time constant then
  grow well beyond the cell's: in `tests/test_identify.py` a slope error of 0.1 V/Ah triples
  both, and with the correction the fit recovers every parameter within 2 %. The correction only
  serves the fit; the model uses the curve of section 2.
- **Identifiability.** A time constant can only be identified from a relaxation at least as long
  as itself. A level whose tau2 is longer than the longest rest in its window is not used. This
  drops the lowest state of charge at 10, 25 and 40 °C, whose window ends with a 10-minute rest
  and where the fit put tau2 at 634 to 934 s.

`tests/test_identify.py` generates the voltage of a cell with known parameters and checks that
the fit recovers all six within 2 %, at -20 and 25 °C.

The parameters at the state of charge nearest half full:

<!-- generated: parameters -->
| Chamber | Cell | R0 | R1 | tau1 | R2 | tau2 | i0 | Fit error (window RMS) |
|---|---|---|---|---|---|---|---|---|
| -20 °C | -19.4 °C | 57.1 mΩ | 38.8 mΩ | 0.7 s | 182 mΩ | 234 s | 0.235 A | 9.3 mV |
| -10 °C | -10.5 °C | 47.3 mΩ | 10.2 mΩ | 4.2 s | 108 mΩ | 174 s | 0.929 A | 8.2 mV |
| 0 °C | -0.4 °C | 32.6 mΩ | 8.0 mΩ | 5.8 s | 84 mΩ | 187 s | 2.94 A | 5.3 mV |
| 10 °C | 9.2 °C | 25.9 mΩ | 6.3 mΩ | 6.0 s | 52 mΩ | 131 s | 14.3 A | 3.4 mV |
| 25 °C | 24.0 °C | 17.6 mΩ | 5.9 mΩ | 8.2 s | 33 mΩ | 130 s | 13.4 A | 2.6 mV |
| 40 °C | 38.6 °C | 14.7 mΩ | 3.6 mΩ | 4.2 s | 18 mΩ | 64 s | 13.4 A | 2.2 mV |
<!-- end generated -->

i0 rises from 0.2 A at -20 °C to 13 to 14 A from 10 °C up, as the Arrhenius law has it. With
i0 = 13.4 A, its value at 25 °C, the charge-transfer term amounts to 1.9 mΩ at small currents
(RT/(F i0)), against 17.6 mΩ for R0, so there i0 is weakly determined (in 10 of the 60 levels
used, all at 0 °C and above, the fit reaches the 100 A bound) and the term hardly matters.

## 4. Two circuits

Every step is done twice: with the charge-transfer term, and without it (the textbook circuit of
two RC pairs, i0 set so large that the term is below a nanovolt). The second shows what the term
adds; section 6 lists both.

## 5. Validation

Each drive-cycle test starts from a full cell that has rested at the chamber temperature. The
model gets the measured current and the measured case temperature, starts from rest with nothing
removed, and predicts the voltage, which is compared with the measurement sample by sample over
the whole test, including the rest at its end.

**Protocol.** The first model, without the two choices of section 3, was run once on all 62
tests. Its median error was 57.1 mV, and much of it came after the drive: in the median test,
40 % of its squared error lies in the rest after the drive and 15 % in the last tenth of the
discharge. The tests were then split: the Mixed1-4 cycles (20 tests) became the development set,
on which the candidate changes were compared, and the other 42 tests the test set, run only with
the final model. On the development set:

<!-- generated: development -->
| Model | Levels used | Median error | RMS of the per-test errors |
|---|---|---|---|
| First: no slope correction, every level | 63 | 60.6 mV | 73.8 mV |
| Slope correction only | 63 | 46.8 mV | 50.4 mV |
| Identifiability rule only | 59 | 38.4 mV | 43.4 mV |
| Both (the model) | 60 | 29.8 mV | 39.9 mV |
<!-- end generated -->

`tools/compare_variants.py` reruns these comparisons from the raw data
(`data/development.json`). They were first made with the -10 °C Mixed4 test in the development
set; a gap in its data, found later ([data.md](data.md)), took it out of the comparisons and the
results alike, and the figures here are for the tests left.

**Results.** Median RMS error per test:

<!-- generated: results -->
| Chamber temperature | Tests | Median error, development set | Median error, test set | Median error, all tests | Worst test | Median error, two RC pairs only |
|---|---|---|---|---|---|---|
| -20 °C | 12 | 63.6 mV | 60.0 mV | 60.7 mV | 87.2 mV | 69.7 mV |
| -10 °C | 11 | 45.6 mV | 42.8 mV | 43.6 mV | 74.6 mV | 46.4 mV |
| 0 °C | 11 | 26.6 mV | 26.1 mV | 26.6 mV | 50.7 mV | 25.5 mV |
| 10 °C | 10 | 29.3 mV | 23.8 mV | 26.2 mV | 51.9 mV | 26.1 mV |
| 25 °C | 11 | 27.9 mV | 20.7 mV | 27.0 mV | 55.8 mV | 26.9 mV |
| 40 °C | 7 | 18.0 mV | 15.4 mV | 16.7 mV | 31.1 mV | 16.6 mV |
| **All** | **62** | **29.8 mV** | **28.6 mV** | **29.0 mV** | **87.2 mV** | **29.3 mV** |
<!-- end generated -->

The test set does as well as the development set (median 28.6 against 29.8 mV), so the choices
did not merely fit the development cycles.

**A check against the dataset's own report.** The dataset's technical report gives the
10-second discharge resistance at 50 % state of charge: 179.3, 89.8, 53.0, 36.7, 27.2 and
23.6 mΩ from -20 to 40 °C, with pulses of 0.25C at -20 °C, 0.5C at -10 °C and 1C above. Read from
the raw pulses at the same state of charge, the five values at -20, -10, 0, 25 and 40 °C agree
within 0.5 mΩ; at 10 °C the 1C pulse there reads 38.0 mΩ, 1.3 mΩ above the report.

**Where the error comes from.** See the README: the end of discharge from 10 °C up, charging
during regenerative braking in the cold, and the hard accelerations of US06. There, a sample
counts as charging or discharging when more than 0.3 A flows, and the end of discharge is the
last tenth of the charge a test removes (`celllab/validation.py`; `data/validation.json` holds
these figures for every test). Heating of the cell's core above its case was checked as another
cause and ruled out: feeding the model the case temperature plus 2, 4 or 6 °C raises the median
error of the twelve -20 °C tests from 60.7 mV to 79.1, 105.8 and 135.9 mV.

## 6. Every test

<!-- generated: every_test -->
| °C | Test | Set | Hours | Ah removed | RMS error | 95th percentile | Largest | RMS, two RC pairs only |
|---|---|---|---|---|---|---|---|---|
| -20 | UDDS | test | 2.28 | 1.59 | 47.7 mV | 93 mV | 241 mV | 37.7 mV |
| -20 | HWFET | test | 0.93 | 1.59 | 53.7 mV | 122 mV | 221 mV | 66.4 mV |
| -20 | LA92 | test | 1.46 | 1.59 | 58.6 mV | 115 mV | 288 mV | 53.0 mV |
| -20 | US06 | test | 0.77 | 1.59 | 87.2 mV | 170 mV | 331 mV | 135.1 mV |
| -20 | Mixed1 | development | 1.26 | 1.59 | 60.1 mV | 128 mV | 329 mV | 71.5 mV |
| -20 | Mixed2 | development | 1.20 | 1.59 | 56.7 mV | 120 mV | 316 mV | 69.3 mV |
| -20 | Mixed3 | development | 1.25 | 1.54 | 68.8 mV | 130 mV | 298 mV | 79.0 mV |
| -20 | Mixed4 | development | 1.28 | 1.54 | 67.0 mV | 130 mV | 320 mV | 70.1 mV |
| -20 | Mixed5 | test | 1.26 | 1.54 | 61.4 mV | 118 mV | 246 mV | 65.0 mV |
| -20 | Mixed6 | test | 1.23 | 1.54 | 70.5 mV | 147 mV | 332 mV | 82.7 mV |
| -20 | Mixed7 | test | 1.13 | 1.54 | 73.5 mV | 151 mV | 291 mV | 87.9 mV |
| -20 | Mixed8 | test | 1.30 | 1.54 | 56.1 mV | 110 mV | 315 mV | 53.1 mV |
| -10 | UDDS | test | 3.43 | 2.16 | 28.0 mV | 52 mV | 211 mV | 29.3 mV |
| -10 | HWFET | test | 1.25 | 2.15 | 42.0 mV | 87 mV | 213 mV | 44.5 mV |
| -10 | LA92 | test | 2.00 | 2.15 | 38.8 mV | 77 mV | 258 mV | 36.0 mV |
| -10 | US06 | test | 0.89 | 2.13 | 74.6 mV | 143 mV | 261 mV | 77.8 mV |
| -10 | Mixed1 | development | 1.74 | 2.13 | 45.6 mV | 89 mV | 224 mV | 50.7 mV |
| -10 | Mixed2 | development | 1.81 | 2.13 | 43.2 mV | 90 mV | 260 mV | 47.9 mV |
| -10 | Mixed3 | development | 1.53 | 2.11 | 52.4 mV | 101 mV | 242 mV | 53.0 mV |
| -10 | Mixed5 | test | 1.67 | 2.12 | 43.6 mV | 86 mV | 286 mV | 43.3 mV |
| -10 | Mixed6 | test | 1.55 | 2.11 | 55.3 mV | 119 mV | 301 mV | 57.4 mV |
| -10 | Mixed7 | test | 1.55 | 2.11 | 47.5 mV | 100 mV | 252 mV | 46.4 mV |
| -10 | Mixed8 | test | 1.87 | 2.11 | 38.9 mV | 76 mV | 273 mV | 39.4 mV |
| 0 | UDDS | test | 3.90 | 2.35 | 17.6 mV | 34 mV | 100 mV | 19.2 mV |
| 0 | HWFET | test | 1.38 | 2.35 | 21.0 mV | 45 mV | 97 mV | 23.0 mV |
| 0 | LA92 | test | 2.27 | 2.35 | 21.6 mV | 43 mV | 143 mV | 22.5 mV |
| 0 | US06 | test | 0.94 | 2.36 | 50.7 mV | 101 mV | 185 mV | 48.6 mV |
| 0 | Mixed1 | development | 1.87 | 2.35 | 26.6 mV | 59 mV | 191 mV | 28.2 mV |
| 0 | Mixed2 | development | 2.01 | 2.35 | 23.4 mV | 45 mV | 129 mV | 24.8 mV |
| 0 | Mixed4 | development | 1.89 | 2.33 | 32.2 mV | 69 mV | 181 mV | 33.0 mV |
| 0 | Mixed5 | test | 1.81 | 2.33 | 25.1 mV | 52 mV | 148 mV | 25.3 mV |
| 0 | Mixed6 | test | 1.74 | 2.33 | 33.4 mV | 82 mV | 193 mV | 34.1 mV |
| 0 | Mixed7 | test | 1.71 | 2.33 | 27.1 mV | 59 mV | 166 mV | 25.5 mV |
| 0 | Mixed8 | test | 2.11 | 2.33 | 28.0 mV | 50 mV | 185 mV | 29.3 mV |
| 10 | UDDS | test | 4.14 | 2.42 | 14.7 mV | 27 mV | 137 mV | 15.0 mV |
| 10 | HWFET | test | 1.47 | 2.42 | 26.4 mV | 62 mV | 123 mV | 26.2 mV |
| 10 | US06 | test | 1.08 | 2.49 | 51.9 mV | 117 mV | 249 mV | 51.0 mV |
| 10 | Mixed1 | development | 2.01 | 2.48 | 33.5 mV | 82 mV | 242 mV | 33.4 mV |
| 10 | Mixed2 | development | 2.16 | 2.48 | 25.9 mV | 61 mV | 162 mV | 25.9 mV |
| 10 | Mixed4 | development | 2.05 | 2.36 | 29.3 mV | 70 mV | 168 mV | 29.1 mV |
| 10 | Mixed5 | test | 1.87 | 2.36 | 28.7 mV | 67 mV | 183 mV | 28.4 mV |
| 10 | Mixed6 | test | 2.05 | 2.36 | 23.8 mV | 52 mV | 126 mV | 23.6 mV |
| 10 | Mixed7 | test | 1.93 | 2.36 | 21.2 mV | 46 mV | 133 mV | 20.4 mV |
| 10 | Mixed8 | test | 2.26 | 2.36 | 18.6 mV | 37 mV | 104 mV | 18.7 mV |
| 25 | UDDS | test | 4.43 | 2.59 | 12.9 mV | 25 mV | 137 mV | 12.9 mV |
| 25 | LA92 | test | 2.80 | 2.59 | 20.7 mV | 40 mV | 180 mV | 20.7 mV |
| 25 | US06 | test | 1.12 | 2.59 | 55.8 mV | 115 mV | 284 mV | 55.6 mV |
| 25 | Mixed1 | development | 2.15 | 2.59 | 28.4 mV | 67 mV | 187 mV | 28.3 mV |
| 25 | Mixed2 | development | 2.20 | 2.59 | 30.3 mV | 48 mV | 225 mV | 30.2 mV |
| 25 | Mixed3 | development | 2.05 | 2.56 | 27.0 mV | 63 mV | 123 mV | 26.9 mV |
| 25 | Mixed4 | development | 2.25 | 2.56 | 27.3 mV | 68 mV | 166 mV | 27.2 mV |
| 25 | Mixed5 | test | 2.00 | 2.56 | 28.6 mV | 56 mV | 180 mV | 28.4 mV |
| 25 | Mixed6 | test | 2.17 | 2.56 | 19.3 mV | 45 mV | 102 mV | 19.2 mV |
| 25 | Mixed7 | test | 2.03 | 2.56 | 21.7 mV | 47 mV | 100 mV | 21.5 mV |
| 25 | Mixed8 | test | 2.39 | 2.56 | 18.6 mV | 49 mV | 100 mV | 18.6 mV |
| 40 | UDDS | test | 4.42 | 2.53 | 11.8 mV | 34 mV | 76 mV | 11.8 mV |
| 40 | HWFET | test | 1.55 | 2.53 | 16.7 mV | 42 mV | 64 mV | 16.6 mV |
| 40 | LA92 | test | 2.74 | 2.53 | 14.1 mV | 36 mV | 78 mV | 14.0 mV |
| 40 | US06 | test | 1.11 | 2.53 | 31.1 mV | 75 mV | 138 mV | 31.0 mV |
| 40 | Mixed1 | development | 2.09 | 2.53 | 18.2 mV | 43 mV | 119 mV | 18.0 mV |
| 40 | Mixed2 | development | 2.19 | 2.53 | 15.8 mV | 40 mV | 105 mV | 15.9 mV |
| 40 | Mixed3 | development | 1.88 | 2.37 | 18.0 mV | 43 mV | 108 mV | 17.8 mV |
<!-- end generated -->

## 7. The virtual lab

The tests drove the cell with a power profile "calculated for a single LG HG2 cell in a compact
electric vehicle" (the dataset's readme), not with a current. `data/profiles.csv` holds one
period of each standard cycle as the 40 °C tests applied it (the only temperature with all four
usable), found as the peak of the power trace's autocorrelation: 1370 s (UDDS), 766 s (HWFET),
1438 s (LA92) and 601 s (US06). The tests at the other temperatures follow the same profiles
(correlation 0.93 to 0.999 with the 40 °C test over the first period), within limits the
testers set on the current. They held the discharge current to 6 A at -20 °C and 12 A at
-10 °C, and the charging current of regenerative braking to 1.5 A at -20 °C, 3 A at -10 and
0 °C and 6 A from 10 °C up; in the data the current sits at these values for long stretches and
passes them by at most 0.3 A, briefly. From 0 °C up the discharge followed the demand, up to
18 A. And the cycler did not let the voltage fall below 2.8 V.

The lab does the same. Each second the current is the one that gives the demanded power at the
terminals, within the current limits of the nearest tested temperature at or below the one
chosen; charging is also capped at 4.2 V, and a discharge the cell cannot give above 2.8 V is
cut to what it gives at 2.8 V. The cycle is repeated, and the drive ends with the first cycle in
which the cell gives less than 90 % of the discharge energy the cycle demands, or when the charge
removed reaches the end of the open-circuit curve at that temperature. The 90 % is a definition
of the lab, not a property of the cell.

As a check of this power-limited mode: in the -20 °C US06 test the limits held the cell to 82 %
of the first period's discharge energy; the lab, with the same demand and limits at -20 °C,
gives 79 %. The model's voltage runs low on US06 (section 5), so at 6 A it gives a little less
power than the cell.

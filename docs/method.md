# Method

This is how I built the model from the test data and how I checked it. The data itself and its
problems are in [data.md](data.md). The tables marked as generated are written by
`tools/update_docs.py` from the files in `data/`, and `tests/test_docs.py` fails if they get out
of date. The same test checks the other numbers on this page against `data/`, and
`tests/test_raw_data.py` checks the ones about the raw data.

## 1. The model

With the current i positive on charge and q the charge removed since the cell was full:

    v = OCV(q, T) + R0 i + eta(i) + u1 + u2
    eta(i) = (2 R T / F) asinh(i / (2 i0))            charge transfer (Butler-Volmer, alpha = 1/2)
    du_k/dt = (R_k i - u_k) / tau_k,   k = 1, 2        two RC pairs

R0 is the ohmic resistance, the instant jump in voltage when the current changes. The
Butler-Volmer term is the overpotential of the reaction at the electrode surfaces. At small
currents it acts like a resistance RT/(F i0), and at large currents it grows only
logarithmically. That is why a cold cell's resistance gets smaller as the pulse gets bigger (the
dataset's report shows this too). The two RC pairs are the slower polarisation, one over seconds
and one over minutes.

The RC pairs are stepped exactly over each sample interval, with the current held:
u[n+1] = a u[n] + R (1 - a) i[n], a = exp(-dt/tau). So the result doesn't depend on the step
length (`tests/test_ecm.py` checks this against the exact step response). R = 8.314462618
J/(mol K) and F = 96485.33212 C/mol are the exact SI values to ten significant digits.

R0, R1, tau1, R2, tau2 and i0 are stored as tables over q at each of the six test temperatures.
Between states of charge they are interpolated linearly in q. Between temperatures their
logarithm is interpolated linearly in 1/T, which is the Arrhenius form for thermally activated
processes. The open-circuit voltage is interpolated linearly in temperature. Outside the tested
range the values are held at the nearest end.

## 2. Open-circuit voltage

Two tests measure it, and neither is enough on its own. The HPPC test rests the cell for an hour
after each of its 9 to 11 steps down in state of charge. The voltage at the end of each rest,
and at the start of the test, is the open-circuit voltage after discharging, but only at those
10 to 12 points. The C/20 test discharges the cell at 0.15 A and traces the whole curve, but it
does it under current, so it sits below the open-circuit voltage by the cell's polarisation at
0.15 A.

So I take the shape of the C/20 discharge and move it onto the rest points. The curve is the
C/20 voltage plus an offset that goes through every rest point, interpolated between them with a
monotone cubic (PCHIP). To choose this, I predicted each interior rest point from the others
(leave one out, 56 points over the six temperatures):

| Construction | RMS error | Largest error |
|---|---|---|
| C/20 shape moved onto the rest points (used) | 8.9 mV | 42 mV |
| Monotone cubic through the rest points alone | 17.8 mV | 40 mV |
| Straight lines between the rest points | 25.6 mV | 70 mV |

The model itself uses every rest point, so between the points it is better than the
leave-one-out numbers. The largest error at each temperature is at one of the three lowest states
of charge predicted, near empty, where the curve is steepest.

I only use the discharge half of the C/20 test. At 0.15 A the cycler's current accuracy (0.1 %
of its 75 A range, ±75 mA) is half the current, and the charge counted on the way down and on
the way back up differs by up to 0.19 Ah. The HPPC steps, at 0.87 to 0.9 A, agree with the C/20
discharge: at 25 °C, where both end at 2.8 V, they remove 2.776 and 2.779 Ah.

## 3. Fitting

At every state of charge the HPPC test runs four pulse pairs. Each one is a 10 s discharge
pulse, 40 s of rest, a 10 s charge pulse and 10 minutes of rest. Then comes a 0.3C discharge to
the next state of charge and an hour of rest. The discharge pulses are 1, 2, 4 and 6C from 0 °C
up, 0.5 to 4C at -10 °C and 0.25 to 2C at -20 °C (1C is 3 A, and 2.9 A at 10 °C). The charge
pulses go up to 2C from 10 °C up, 1C at 0 and -10 °C and 0.5C at -20 °C.

One fit window goes from the end of one hour-long rest to the end of the next. A window without
a charge pulse has no pulse set and is dropped. If the step in a window discharges the cell to
the 2.8 V cut-off, the window ends before that step, because the cell is far from linear there.

In each window the parameters are fitted to the measured voltage, sample by sample, by least
squares. For given tau1, tau2 and i0 the voltage is linear in R0, R1 and R2. So these are solved
exactly with non-negative least squares at every trial (variable projection), and the search
only runs over tau1 (0.1-20 s), tau2 (20-2000 s) and i0 (0.005-100 A), from twelve starting
points, keeping the best. The window starts from rest, with the RC voltages at zero.

I made two choices after a first run of the model on all the drive cycles (section 5):

- A straight-line correction to the open-circuit voltage inside each window, fitted together
  with the resistances. Without it, an error in the slope of the open-circuit curve inside the
  window (largest near empty) gets taken up by the slow RC pair, and its resistance and time
  constant come out much bigger than the cell's. In `tests/test_identify.py` a slope error of
  0.1 V/Ah triples both, and with the correction the fit gets every parameter back within 2 %.
  The correction is only for the fit. The model uses the curve from section 2.
- Identifiability. A time constant can only be found from a relaxation at least as long as
  itself. So a level whose tau2 is longer than the longest rest in its window is not used. This
  drops the lowest state of charge at 10, 25 and 40 °C. Their windows end with a 10-minute rest,
  and the fit put tau2 at 634 to 934 s there.

`tests/test_identify.py` also makes the voltage of a cell with known parameters and checks that
the fit gets all six back within 2 %, at -20 and 25 °C.

The parameters at the state of charge closest to half full:

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

i0 rises from 0.2 A at -20 °C to 13 to 14 A from 10 °C up, as the Arrhenius law says. With
i0 = 13.4 A, its value at 25 °C, the charge-transfer term is 1.9 mΩ at small currents
(RT/(F i0)), against 17.6 mΩ for R0. So when the cell is warm, i0 is not well determined (in 10
of the 60 levels used, all at 0 °C and above, the fit hits the 100 A bound), but there the term
hardly matters.

## 4. Two circuits

I did every step twice: with the charge-transfer term, and without it (the usual textbook
circuit with two RC pairs, with i0 so large that the term is below a nanovolt). The second one
shows what the term adds. Section 6 lists both.

## 5. Validation

Each drive-cycle test starts from a full cell that has rested at the chamber temperature. The
model gets the measured current and the measured case temperature, starts from rest with nothing
removed, and predicts the voltage. That is compared with the measurement sample by sample over
the whole test, including the rest at the end.

### How the choices were made

My first version of the model had neither of the two choices from section 3. I ran it once on
all 62 tests. Its median error was 57.1 mV, and a lot of it came after the drive: in the median
test, 40 % of its squared error lies in the rest after the drive and 15 % in the last tenth of
the discharge. Then I split the tests. The Mixed1-4 cycles (20 tests) became the development
set, where I compared the candidate changes. The other 42 tests became the test set, which I
only ran with the final model. On the development set:

<!-- generated: development -->
| Model | Levels used | Median error | RMS of the per-test errors |
|---|---|---|---|
| First: no slope correction, every level | 63 | 60.6 mV | 73.8 mV |
| Slope correction only | 63 | 46.8 mV | 50.4 mV |
| Identifiability rule only | 59 | 38.4 mV | 43.4 mV |
| Both (the model) | 60 | 29.8 mV | 39.9 mV |
<!-- end generated -->

`tools/compare_variants.py` reruns these comparisons from the raw data
(`data/development.json`). I first ran them with the -10 °C Mixed4 test in the development set.
Later I found the gap in its data ([data.md](data.md)) and took it out of both the comparisons
and the results, so the numbers here are without it.

### Results

Median RMS error per test:

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
did not just fit the development cycles.

### Check against the dataset's report

The dataset's technical report gives the 10 s discharge resistance at 50 % state of charge:
179.3, 89.8, 53.0, 36.7, 27.2 and 23.6 mΩ from -20 to 40 °C, with pulses of 0.25C at -20 °C,
0.5C at -10 °C and 1C above. Reading the raw pulses at the same state of charge, the values at
-20, -10, 0, 25 and 40 °C agree within 0.5 mΩ. At 10 °C the 1C pulse gives 38.0 mΩ, 1.3 mΩ above
the report.

### Where the error comes from

The README has the summary: the end of discharge from 10 °C up, charging during regenerative
braking in the cold, and the hard accelerations of US06. For those numbers a sample counts as
charging or discharging when more than 0.3 A flows, and the end of discharge is the last tenth
of the charge a test removes (`celllab/validation.py`; `data/validation.json` has the figures
for every test).

I also checked if the cell's core being warmer than its case could explain the error in the
cold. It can't: feeding the model the case temperature plus 2, 4 or 6 °C raises the median
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
electric vehicle" (from the dataset's readme), not with a current. `data/profiles.csv` has one
period of each standard cycle as the 40 °C tests applied it (40 °C is the only temperature where
all four are usable). I found the periods from the peak of the power signal's autocorrelation:
1370 s (UDDS), 766 s (HWFET), 1438 s (LA92) and 601 s (US06). The tests at the other
temperatures follow the same profiles (correlation 0.93 to 0.999 with the 40 °C test over the
first period), but within limits the testers set on the current. They held the discharge current
to 6 A at -20 °C and 12 A at -10 °C, and the charging current of regenerative braking to 1.5 A
at -20 °C, 3 A at -10 and 0 °C and 6 A from 10 °C up. In the data the current sits at these
values for long stretches and goes past them by at most 0.3 A, only for a moment. From 0 °C up
the discharge followed the demand, up to 18 A. And the cycler never let the voltage fall below
2.8 V.

The lab does the same. Every second the current is the one that gives the demanded power at the
terminals, within the current limits of the closest tested temperature at or below the one you
pick. Charging is also capped at 4.2 V, and a discharge the cell can't give above 2.8 V is cut to
what it gives at 2.8 V. The cycle repeats, and the drive ends with the first cycle where the
cell gives less than 90 % of the discharge energy the cycle asks for, or when the charge removed
reaches the end of the open-circuit curve at that temperature. The 90 % is my definition for the
lab, not a property of the cell.

As a check: in the -20 °C US06 test the limits held the cell to 82 % of the first period's
discharge energy. The lab, with the same demand and limits at -20 °C, gives 79 %. The model's
voltage runs low on US06 (section 5), so at 6 A it gives a bit less power than the real cell.

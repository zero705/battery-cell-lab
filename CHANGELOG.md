# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-20

### Added

- Download of the McMaster LG 18650HG2 test data (206 files), each checked against the SHA-256
  that Mendeley Data publishes, and an audit of every file; eight unusable drive-cycle tests are
  left out, each for a stated reason.
- Open-circuit voltage from the C/20 discharge moved onto the HPPC rest voltages, chosen by
  predicting each rest point from the others.
- Equivalent circuit model with a Butler-Volmer charge-transfer term and two RC pairs, advanced
  exactly for any step length, with its parameters interpolated in charge and, along the
  Arrhenius law, in temperature.
- Identification of the parameters at every state of charge of the HPPC test at six
  temperatures, by variable projection with non-negative least squares from several starting
  points, with a local correction of the open-circuit slope and a rule that leaves out levels
  whose slow time constant the test cannot show; a script reruns the comparisons that chose
  these two.
- Validation on 62 drive-cycle tests from -20 to 40 °C, split into a development set and a test
  set, for the model with and without the charge-transfer term, with where the error sits in
  every test.
- A virtual lab that drives the model with the tests' power profiles, within the tests' limits
  on the current either way and the cycler's hold at 2.8 V.
- Streamlit app: a pulse and the parts of the circuit, every parameter, the virtual lab, the
  same drive at six temperatures, and every validation test.
- Documentation of the method and the data; the tables in the documents are generated from the
  data, and tests check every number the documents and comments state, recomputing those about
  the raw data from it.
- Test suite with 100 % coverage of the package, continuous integration on Linux and Windows with
  Python 3.10 to 3.14, a test of the app with its pinned deployment requirements, a monthly
  download and check of the raw data, a dependency audit and CodeQL.

[0.1.0]: https://github.com/zero705/battery-cell-lab/releases/tag/v0.1.0

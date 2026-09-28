# Security policy

## Reporting a vulnerability

Please report a security problem privately, through GitHub's private vulnerability reporting
for this repository (the **Security** tab, then **Report a vulnerability**), and not in a public
issue. Include the file or page concerned, the steps that reproduce the problem and the impact
you expect.

Only the latest version on the `main` branch is supported.

## What the project exposes, and how it is protected

- **The app** has no accounts and stores nothing. It accepts no uploads and no free text, and
  it makes no outbound requests. Every input is a choice from a fixed list or a bounded slider,
  and the server checks each value again before using it, since a browser can send any value:
  a file is read only for a test listed in `data/validation.json`. Every number is computed
  from the files in `data/`, and the caches that hold results have a fixed size. No HTML is
  rendered, and a link is made only for a plain HTTPS address. Visitors see a generic message
  if something fails; details go to the server log only (`.streamlit/config.toml`).
- **The scripts in `tools/`** download the dataset from Mendeley Data. They accept only
  addresses of this dataset's files on Mendeley Data, over HTTPS (redirects included), cap the
  size of every download, write only plain file names inside `data/raw/`, and write a file
  only if its SHA-256 matches the one Mendeley publishes (listed in `data/dataset.json`); a
  file is written to a temporary name first and moved into place only when complete.
- **The supply chain.** The app's deployment dependencies are pinned in `requirements.txt` and
  tested in CI as pinned. Dependabot proposes updates to them and to the pinned GitHub Actions
  once a release is a week old. CI audits the dependencies with pip-audit and lints the code
  with the flake8-bandit security rules. CodeQL scans the Python code and the workflows. The
  workflows can only read the repository (CodeQL may also upload its findings to code
  scanning), use no secrets, and keep no credentials. The Actions they call are pinned to
  full commit SHAs.

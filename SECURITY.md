# Security policy

## Reporting a problem

If you find a security problem, please report it privately through GitHub's private
vulnerability reporting (the **Security** tab, then **Report a vulnerability**), not in a public
issue. Please say which file or page it is about, how to reproduce it and what you think the
impact is.

Only the latest version on the `main` branch is supported.

## What the project exposes and how it is protected

### The app

It has no accounts and stores nothing. It takes no uploads and no free text, and it doesn't make
requests to other sites. Every input is a choice from a fixed list or a slider with limits, and
the server checks each value again before using it, because a browser can send anything. A file
is only read for a test that is listed in `data/validation.json`. All numbers come from the files
in `data/`, and the caches that keep results have a fixed size. No HTML is rendered, and a link is
only made for a plain HTTPS address. If something fails, visitors only see a generic message, and
the details go to the server log (`.streamlit/config.toml`).

### The download scripts

The scripts in `tools/` download the dataset from Mendeley Data. They only accept addresses of
this dataset's files on Mendeley Data, over HTTPS (redirects too), limit the size of every
download, only write plain file names inside `data/raw/`, and only keep a file if its SHA-256
matches the one Mendeley publishes (listed in `data/dataset.json`). A file is written under a
temporary name first and only renamed when it is complete.

### Dependencies and CI

The app's deployment dependencies are pinned in `requirements.txt`, and CI tests that exact set.
Dependabot suggests updates for them and for the GitHub Actions once a release is a week old. CI
checks the dependencies with pip-audit and lints the code with the flake8-bandit security rules,
and CodeQL scans the Python code and the workflows. The workflows can only read the repository
(CodeQL can also upload its results to code scanning), use no secrets and keep no credentials.
The Actions they use are pinned to full commit SHAs.

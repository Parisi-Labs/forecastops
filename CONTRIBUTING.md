# Contributing to ForecastOps

Thanks for your interest in improving ForecastOps. This is an early
(`0.x`) project, so APIs may still change — issues and pull requests are
welcome.

## Development setup

```bash
git clone https://github.com/Parisi-Labs/forecastops.git
cd forecastops
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a pull request

Run the same checks CI runs:

```bash
ruff check .
mypy forecastops
pytest
```

All three must pass. `pytest` runs against an isolated local store, so it
won't touch any real `.forecastops` directory.

## Guidelines

- **Keep changes focused.** One logical change per pull request; it makes
  review and the changelog easier.
- **Add tests** for new behavior and for any bug you fix — there's a
  regression test for nearly every fix in `tests/`.
- **Update `CHANGELOG.md`** under an `Unreleased` section when your change
  is user-visible.
- **Respect the privacy model.** ForecastOps is local-first: don't add
  outbound network calls, and never put raw forecast points into telemetry.
- **Match the existing style.** `ruff` enforces formatting and imports
  (line length 100, target Python 3.10).

## Reporting bugs and requesting features

Use the issue templates. For anything security-related, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

By contributing, you agree that your contributions are licensed under the
project's [Apache-2.0 License](LICENSE).

# Security Policy

## Supported versions

ForecastOps is in early development. Security fixes are applied to the
latest released version on the `0.x` line.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately via GitHub's
[private vulnerability reporting](https://github.com/Parisi-Labs/forecastops/security/advisories/new)
("Report a vulnerability" under the repository's Security tab). We aim to
acknowledge reports within a few business days.

## Security model

ForecastOps is local-first by design, and its defaults reflect that:

- The local UI binds to `127.0.0.1` and **refuses to bind to a non-loopback
  host unless `--allow-remote` is passed explicitly**. The UI is read-only
  and ships no authentication — if you expose it with `--allow-remote`, you
  are responsible for placing it behind your own network controls.
- ForecastOps makes no outbound network calls.
- OpenTelemetry export is off by default and, when enabled, emits only
  aggregate metric values and identifying attributes — never raw forecast
  points.
- Forecast data is stored unencrypted in the configured local store; treat
  that directory with the same care as the underlying data.

When reporting, please note whether the issue involves the default
loopback configuration or only the opt-in `--allow-remote` mode.

# Changelog

All notable changes to this project are documented in this file. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-07-20

### Fixed

- Percent-encode path parameters (workflow, session, call, phone-number and
  webhook-endpoint identifiers) before interpolating them into request URLs, so a
  value containing `/`, `?`, `#` or `..` can no longer traverse paths or inject
  query/fragment components.
- `verify_webhook()` no longer raises `TypeError` on a non-ASCII `v1=` signature;
  the constant-time comparison now runs on bytes and returns `False` instead.

## [0.1.0] - 2026-07-19

### Added

- Initial release.
- `Glytos` client with `workflows`, `calls`, `phone_numbers`, `sessions` and
  `webhooks` resources, plus a generic `request()` for any other endpoint.
- `verify_webhook()` for webhook signature verification.
- Typed (`py.typed`) and built on `httpx`.

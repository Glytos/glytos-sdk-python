# Changelog

All notable changes to this project are documented in this file. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `dnc` - the numbers your organization must not call: `dnc.list`, `dnc.add`,
  `dnc.import_`, `dnc.set_scope`, `dnc.remove`. Every outbound call is checked
  against this list, whether it comes from a campaign or from `calls.create`.
- `campaigns.stop`, `campaigns.delete` and `campaigns.add_contacts` (upload a
  contact list as CSV text rather than serving it over HTTP).
- `campaigns.preview_suppression` - how many of a contact list each suppression
  policy would reach, including how many of those people asked on a call not to
  be contacted again.
- `campaigns.create` gained `contacts_csv`, `scheduled_at` (a `datetime` or an
  ISO 8601 string), `call_window_start`/`call_window_end`, `timezone`,
  `suppression_policy` and `override_caller_requests`.

### Fixed

- `campaigns.create` typed `contacts` as a sequence of dicts, which the API
  rejects with a 422. It is a sequence of phone numbers.

## [0.2.1] - 2026-08-02

### Fixed

- `glytos.__version__` reported the previous release. It now reads the installed
  distribution's metadata, so it can no longer drift from `pyproject.toml`.

## [0.2.0] - 2026-08-02

### Added

- `threads` - conversations with a text agent: `threads.create`,
  `threads.retrieve`, `threads.messages.create/list`, `threads.runs.create/stream`.
- Streaming. `threads.runs.stream`, `agents.stream_message` and `chat.stream` yield
  `token` deltas and a terminal `done` carrying the finished run.
- Per-turn `instructions` on every text turn, applied below the agent's own and
  never saved to it.
- File uploads: `chat.upload_file`, `knowledge_base.upload_document`,
  `vector_stores.upload_document`, plus `client.request_form` for any other
  multipart endpoint.
- `folders` and `imports` namespaces, plus `agents.move_to_folder` /
  `agents.remove_from_folder` to file an agent and `agents.export` for the
  portable, secret-free JSON that imports back.
- `agents` as an alias of `workflows`.
- Everything above on `AsyncGlytos` too.

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

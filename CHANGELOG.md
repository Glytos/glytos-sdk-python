# Changelog

All notable changes to this project are documented in this file. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

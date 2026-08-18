# Changelog

All notable changes to this project are documented in this file. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `campaigns.update`, `campaigns.unschedule`, `campaigns.duplicate` and
  `campaigns.export`, on both `Glytos` and `AsyncGlytos`. A rename is accepted at
  any point; the schedule and the calling window can only be changed before a
  campaign starts. `unschedule` is separate because `update` drops anything left
  unset, and clearing a schedule has to send an explicit null.
- Campaigns now report `counts` and `workflow_name`, and creating one returns an
  `imported` receipt. Measure progress against `counts["dialable"]` rather than
  `counts["total"]`: suppressed numbers are never dialed.

- `sip_trunks` - connect a carrier directly over SIP, with no third party in
  between: `presets`, `list`, `create`, `update`, `delete`, `test`. Numbers are
  attached to a registered trunk through `phone_numbers.import_number`, which now
  accepts `sip_trunk_uuid`.
- `integrations` and `integrations.connections` - the destinations an agent or an
  automation can act on, and the named connections holding their credentials.
- `automations` - fire an integration action when an event happens: `list`,
  `create`, `update`, `delete`, `runs`, `test`.
- `test_suites` - `list`, `create`, `delete`, `run`.
- `billing` - `credits`, `transactions`, `usage`. Checking the balance before a
  long outbound run no longer needs a raw `request` call.
- `environments.list`, `providers.list`, `providers.resources`, `api_keys.list`
  /`create`/`delete`, `organizations.retrieve`/`update`/`regions`.
- `knowledge_base.retrieve_document` and `knowledge_base.delete_document`.
  Documents could be created and listed but never read back or removed.
- `tools.discover_mcp` - ask an MCP server what it publishes, instead of
  transcribing its schema by hand.
- `imports.connect` and `imports.pull` - list the agents on another platform with
  its API key, then bring over the ones you pick. The key is never stored.
- `workflows.create` accepts `primary_channel`.

Every addition is on both `Glytos` and `AsyncGlytos`, under the same names.

### Fixed

- The `Tools` docstring said `kind` was http / static / mcp. The API has accepted
  `code`, `integration` and `client` since they shipped, and the docstring now
  says what each of the six does.
- The README's resource table had drifted: it was missing several agent methods
  that shipped some time ago, and did not mention that the async client carries
  the same surface.

## [0.3.0] - 2026-08-09

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

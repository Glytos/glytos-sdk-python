# glytos

[![CI](https://github.com/Glytos/glytos-sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/Glytos/glytos-sdk-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/glytos)](https://pypi.org/project/glytos/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

The official [Glytos](https://glytos.com) server SDK for Python.

Call the Glytos API from your backend with an API key. Build agents once and run
them as **text** or as **voice**: hold a threaded conversation, stream a reply as it
is written, place phone calls, mint browser web-call tokens, manage numbers, and
verify webhooks.

> Never ship an API key to the browser. For in-browser voice, use the `@glytos/web`
> package with a short-lived token you mint here.

## Install

```bash
pip install glytos
```

## Quickstart

```python
from glytos import Glytos

glytos = Glytos(api_key="gly_...")

# List your agents
agents = glytos.agents.list()

# Mint a web-call token for the browser
token = glytos.calls.web_token(workflow_uuid=agents[0]["uuid"])
print(token["token"], token["ws_url"])
```

Use it as a context manager to close the HTTP connection cleanly:

```python
with Glytos(api_key="gly_...") as glytos:
    overview = glytos.request("GET", "/analytics/overview")
```

### Text conversations

An agent is one definition; nothing forces it to do both text and voice. For text,
a thread holds the conversation and a run is one turn on it:

```python
thread = glytos.threads.create(agent=agent_uuid)
run = glytos.threads.runs.create(thread, "What are your opening hours?")
print(run["messages"][-1]["content"])
```

Stream a long answer instead of waiting for it:

```python
for event in glytos.threads.runs.stream(thread, "Summarise the policy"):
    if event.type == "token":
        print(event.delta, end="", flush=True)
    elif event.type == "done":
        print()
```

Extra context for one turn only, applied below the agent's own instructions and
never saved to it:

```python
glytos.threads.runs.create(
    thread,
    "Rate this transcript",
    instructions="Score 1-5 and reply as JSON.",
)
```

Everything above has an async twin on `AsyncGlytos` (`async for` over the stream).

## Resources

| Namespace | Methods |
| --- | --- |
| `glytos.agents` (alias `workflows`) | `list`, `retrieve`, `create`, `rename`, `publish`, `promote`, `duplicate`, `archive`, `delete`, `templates`, `export`, `move_to_folder`, `remove_from_folder`, `versions`, `start_session`, `send_message`, `stream_message`, `run_text` |
| `glytos.threads` | `create`, `retrieve`, `messages.create`, `messages.list`, `runs.create`, `runs.stream` |
| `glytos.folders` | `list`, `create`, `rename`, `delete` |
| `glytos.imports` | `sources`, `create`, `assistant` |
| `glytos.chat` | `token`, `messages`, `stream`, `upload_file` |
| `glytos.calls` | `create`, `list`, `retrieve`, `web_token`, `control` |
| `glytos.phone_numbers` | `search`, `list`, `providers`, `provision`, `import_number`, `instant`, `assign`, `release` |
| `glytos.knowledge_base` | `list_documents`, `create_document`, `upload_document`, `search` |
| `glytos.vector_stores` | `list`, `create`, `retrieve`, `delete`, `upload_document` |
| `glytos.tools` | `list`, `create`, `update`, `delete` |
| `glytos.campaigns` | `list`, `create`, `retrieve`, `start`, `stop`, `delete`, `add_contacts`, `sync_contacts`, `preview_suppression` |
| `glytos.dnc` | `list`, `add`, `import_`, `set_scope`, `remove` |
| `glytos.sessions` | `list` |
| `glytos.analytics` | `overview` |
| `glytos.webhooks` | `list`, `create`, `update`, `delete`, `events`, `deliveries`, `redeliver`, `verify` |

`agents` and `workflows` are the same resource under two names: the product calls
them agents, the API path is `/workflows`. Either works.

### Text and voice are separate

An agent is one definition. Nothing forces it to do both:

- A **text** agent needs only `threads` (or `chat` for a browser widget).
- A **voice** agent adds `calls`, `phone_numbers` and `campaigns`.
- The same agent can do both, if you want it to.

Any endpoint without a dedicated helper is one call away with
`glytos.request(method, path, json=..., params=...)`, or
`glytos.stream(method, path, json=...)` for a Server-Sent Events one.

## Outbound calling

A campaign dials a list of contacts with one agent. Upload the list as CSV text:
the phone column is found by its header or by which column holds phone numbers,
and every other column travels with that contact, so `{{name}}` in the agent's
prompt means the person being called.

```python
from datetime import datetime, timezone
from pathlib import Path

campaign = glytos.campaigns.create(
    name="March outreach",
    workflow_uuid=agent["uuid"],
    from_number="+15551230000",  # must be a number you have connected
    contacts_csv=Path("leads.csv").read_text(encoding="utf-8"),
    scheduled_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    call_window_start="09:00",
    call_window_end="20:00",
    timezone="Europe/Istanbul",
)
```

Left unscheduled, a campaign stays a draft until `start`. `stop` ends it at the
next contact, leaving the undialed ones ready to resume. `retrieve` returns each
contact's outcome and, where one answered, the session it produced.

Every outbound call is checked against your do-not-call list first, whether it
comes from a campaign or from `calls.create`. Agents add to that list themselves
when someone asks not to be contacted again:

```python
glytos.dnc.add("+15551230000", reason="asked on a call")
```

A campaign chooses how much of the list applies. The default, `strict`, honours
all of it. `transactional` still calls people who only refused marketing, which
is what you want for a call about someone's own order. `ignore` skips entries
your organization added for itself, but requests people made on a call still
apply unless you also set `override_caller_requests`. Measure before you choose:

```python
preview = glytos.campaigns.preview_suppression(
    contacts_csv=Path("leads.csv").read_text(encoding="utf-8"),
)
print(
    f"{preview['reached_if_strict']} of {preview['contacts']} reachable; "
    f"{preview['caller_requested']} asked us not to call"
)
```

## Errors

Non-2xx responses raise a `GlytosError` with the API error `code`, HTTP `status`,
and the `request_id`:

```python
from glytos import GlytosError

try:
    glytos.workflows.retrieve("missing")
except GlytosError as err:
    print(err.status, err.code, err.message)
```

## Webhooks

Verify a delivery came from Glytos before trusting it. Pass the **raw** request
body, the `X-Glytos-Signature` header, and your endpoint secret:

```python
from glytos import verify_webhook

# e.g. in a Flask/FastAPI handler
ok = verify_webhook(raw_body, request.headers["X-Glytos-Signature"], webhook_secret)
if not ok:
    abort(400)
```

## License

MIT

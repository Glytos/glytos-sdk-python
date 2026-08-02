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
| `glytos.campaigns` | `list`, `create`, `retrieve`, `start`, `sync_contacts` |
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

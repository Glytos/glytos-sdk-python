# glytos

[![CI](https://github.com/Glytos/glytos-sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/Glytos/glytos-sdk-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/glytos)](https://pypi.org/project/glytos/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

The official [Glytos](https://glytos.com) server SDK for Python.

Call the Glytos API from your backend with an API key: build and run voice agents,
start phone calls, mint browser web-call tokens, manage phone numbers, and verify
webhooks.

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
agents = glytos.workflows.list()

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
| `glytos.workflows` | `list`, `retrieve`, `create`, `publish`, `delete`, `templates`, `session`, `session_events` |
| `glytos.calls` | `create`, `list`, `retrieve`, `web_token`, `control` |
| `glytos.phone_numbers` | `search`, `list`, `provision`, `assign`, `release` |
| `glytos.sessions` | `list` |
| `glytos.webhooks` | `list`, `create`, `delete`, `events`, `verify` |

Any endpoint without a dedicated helper is one call away with
`glytos.request(method, path, json=..., params=...)`.

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

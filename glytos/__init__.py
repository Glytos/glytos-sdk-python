"""Official Glytos server SDK for Python.

Call the Glytos API from your backend with an API key. Build agents once and run
them as text or as voice: hold a threaded conversation, stream a reply as it is
written, place phone calls, mint browser web-call tokens, and verify webhooks.

    from glytos import Glytos

    glytos = Glytos(api_key="gly_...")
    agents = glytos.agents.list()

    thread = glytos.threads.create(agent=agents[0]["uuid"])
    run = glytos.threads.runs.create(thread, "What are your opening hours?")
    print(run["messages"][-1]["content"])

Never ship an API key to the browser. For in-browser voice, use the ``@glytos/web``
package with a short-lived token you mint here via ``calls.web_token(...)``.
"""

from ._client import AsyncGlytos, Glytos, GlytosError, StreamEvent, Thread
from ._webhooks import verify_webhook

__all__ = [
    "AsyncGlytos",
    "Glytos",
    "GlytosError",
    "StreamEvent",
    "Thread",
    "verify_webhook",
]
__version__ = "0.1.1"

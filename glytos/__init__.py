"""Official Glytos server SDK for Python.

Call the Glytos API from your backend with an API key: build and run voice agents,
start phone calls, mint browser web-call tokens, manage phone numbers, and verify
webhooks.

    from glytos import Glytos

    glytos = Glytos(api_key="gly_...")
    agents = glytos.workflows.list()
    token = glytos.calls.web_token(workflow_uuid=agents[0]["uuid"])

Never ship an API key to the browser. For in-browser voice, use the ``@glytos/web``
package with a short-lived token you mint here via ``calls.web_token(...)``.
"""

from ._client import Glytos, GlytosError
from ._webhooks import verify_webhook

__all__ = ["Glytos", "GlytosError", "verify_webhook"]
__version__ = "0.1.1"

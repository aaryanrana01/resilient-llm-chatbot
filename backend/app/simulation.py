"""X-Simulate-Failure test hook.

Header format:  key_1=429  |  key_1=429,key_2=500  |  *=429
Each listed key behaves as if its provider returned that status, for this request only.
"""

from __future__ import annotations

import logging
import re

import litellm

logger = logging.getLogger("app.simulation")

ALLOWED_STATUSES = {429, 500, 502, 503}
WILDCARD = "*"
_KEY_RE = re.compile(r"^(\*|key_[1-9][0-9]*)$")


def parse_simulation_header(value: str | None) -> dict[str, int]:
    """Parse the header into {key_id_or_*: status}. Invalid pairs are ignored (and logged)."""
    rules: dict[str, int] = {}
    if not value:
        return rules
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, status = part.partition("=")
        key, status = key.strip(), status.strip()
        if not sep or not _KEY_RE.match(key) or not status.isdigit() or int(status) not in ALLOWED_STATUSES:
            logger.warning("ignoring invalid X-Simulate-Failure entry: %r", part)
            continue
        rules[key] = int(status)
    return rules


def status_for_key(rules: dict[str, int], key_id: str) -> int | None:
    """An explicit key rule wins over the * wildcard."""
    if key_id in rules:
        return rules[key_id]
    return rules.get(WILDCARD)


def simulated_error(status: int, key_id: str, model: str) -> Exception:
    """Build the same LiteLLM exception a real provider failure would produce."""
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    message = f"simulated HTTP {status} for {key_id} (X-Simulate-Failure)"
    if status == 429:
        return litellm.RateLimitError(message=message, llm_provider=provider, model=model)
    if status == 502:
        return litellm.BadGatewayError(message=message, llm_provider=provider, model=model)
    if status == 503:
        return litellm.ServiceUnavailableError(message=message, llm_provider=provider, model=model)
    return litellm.InternalServerError(message=message, llm_provider=provider, model=model)

"""
title: MCP App Resource Context
author: mcp-app-bridge
version: 0.1.0
required_open_webui_version: 0.5.0
description: >
  Companion filter for the mcp-app-bridge loader. MCP Apps cannot push
  `resource` content blocks (from app.sendMessage / app.updateModelContext)
  through Open WebUI's text-only composer, so the loader stages them in the
  browser's localStorage. This filter's outlet drains that queue after the
  model responds via an `execute` event call and appends a JSON dump of the
  resources to the latest USER message's content. Open WebUI persists outlet
  content changes to the chat record and the frontend re-sends the full message
  history every turn, so the resources become durable context the model sees on
  every subsequent turn. The user message is targeted (not the assistant
  response) because Open WebUI rebuilds assistant messages from their structured
  `output` items for the LLM and discards assistant `content`; user messages
  have no `output`, so their content always reaches the model verbatim.
"""

import base64
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Must match RESOURCE_QUEUE_KEY in the loader (loader.ts).
RESOURCE_QUEUE_KEY = "mcp-app-bridge:resource-queue"

# JS evaluated in the user's browser tab via the `execute` event call. Reads and
# clears the localStorage queue atomically so each resource is injected once.
_READ_AND_CLEAR_JS = (
    "const k = %s;"
    "const v = localStorage.getItem(k);"
    "localStorage.removeItem(k);"
    "return v;"
) % json.dumps(RESOURCE_QUEUE_KEY)


def _is_text_mime(mime: str) -> bool:
    if not mime:
        return False
    mime = mime.lower()
    return (
        mime.startswith("text/")
        or mime in ("application/json", "application/xml")
        or mime.endswith("+json")
        or mime.endswith("+xml")
    )


def _resource_to_text(block: dict) -> tuple[str, str]:
    """Return (name, content) text for a `resource` / `resource_link` block."""
    if block.get("type") == "resource_link":
        uri = block.get("uri", "")
        name = block.get("name") or uri or "resource"
        desc = block.get("description") or ""
        content = f"[Resource link] {name}\nURI: {uri}"
        if desc:
            content += f"\n{desc}"
        return name, content

    res = block.get("resource") or {}
    uri = res.get("uri", "")
    mime = res.get("mimeType") or ""
    name = uri or "resource"

    if isinstance(res.get("text"), str):
        return name, res["text"]

    blob = res.get("blob")
    if isinstance(blob, str):
        if _is_text_mime(mime):
            try:
                return name, base64.b64decode(blob).decode("utf-8", "replace")
            except Exception:
                pass
        return name, f"[Binary resource omitted] URI: {uri} ({mime or 'unknown type'})"

    return name, f"[Resource] URI: {uri} ({mime or 'unknown type'})"


# Marker wrapping the appended JSON dump in the assistant message content.
# Kept distinctive so the block is easy to recognize in the transcript.
_RESOURCE_SUMMARY = "MCP App resources"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Filter execution priority (lower runs first)."
        )
        enabled: bool = Field(
            default=True,
            description="Append staged MCP App resources to the assistant message.",
        )
        max_resources: int = Field(
            default=20, description="Maximum resources to append per turn."
        )

    def __init__(self):
        self.valves = self.Valves()

    async def outlet(
        self,
        body: dict,
        __event_call__: Optional[Callable[[dict], Awaitable[Any]]] = None,
    ) -> dict:
        if not self.valves.enabled or __event_call__ is None:
            return body

        # Pull (and clear) the queued resources from the user's browser tab.
        try:
            raw = await __event_call__(
                {"type": "execute", "data": {"code": _READ_AND_CLEAR_JS}}
            )
        except Exception as e:
            log.debug(f"resource-context: event_call failed: {e}")
            return body

        # event_caller returns {'error': ...} on disconnect/timeout; ignore.
        if not isinstance(raw, str) or not raw.strip():
            return body
        try:
            blocks = json.loads(raw)
        except Exception:
            return body
        if not isinstance(blocks, list) or not blocks:
            return body

        items = []
        for block in blocks[: max(0, self.valves.max_resources)]:
            if not isinstance(block, dict):
                continue
            try:
                name, content = _resource_to_text(block)
            except Exception:
                continue
            if not content:
                continue
            items.append({"name": name, "content": content})

        if not items:
            return body

        # Append the JSON dump to the most recent USER message's content. The
        # middleware persists this content change and the frontend syncs it, so
        # the resources ride along in the history on every subsequent turn.
        #
        # The user message is targeted (not the assistant response) because
        # Open WebUI rebuilds assistant messages from their structured `output`
        # items for the LLM (process_messages_with_output) and discards anything
        # appended to assistant `content`. User messages have no `output`, so
        # their content is always sent to the model verbatim.
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return body

        target = next(
            (
                m
                for m in reversed(messages)
                if isinstance(m, dict) and m.get("role") == "user"
            ),
            None,
        )
        if target is None:
            return body

        dump = json.dumps(items, ensure_ascii=False, indent=2)
        block = (
            f"\n\n<details>\n<summary>{_RESOURCE_SUMMARY}</summary>\n\n"
            f"```json\n{dump}\n```\n</details>"
        )
        target["content"] = (target.get("content") or "") + block
        return body

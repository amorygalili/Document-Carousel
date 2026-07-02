"""
title: MCP App Resource Context
author: mcp-app-bridge
version: 0.1.0
required_open_webui_version: 0.5.0
description: >
  Companion filter for the mcp-app-bridge loader. MCP Apps cannot push
  `resource` content blocks (from app.sendMessage / app.updateModelContext)
  through Open WebUI's text-only composer, so the loader stages them in the
  browser's localStorage. This filter's inlet drains that queue before the
  model is called via an `execute` event call and appends a JSON dump of the
  resources to the latest USER message's content, so the model sees the
  resources in the current turn. The user message is targeted because Open
  WebUI rebuilds assistant messages from their structured `output` items for
  the LLM and discards assistant `content`; user messages have no `output`,
  so their content always reaches the model verbatim.
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
    # "localStorage.removeItem(k);"
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



class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Filter execution priority (lower runs first)."
        )
        enabled: bool = Field(
            default=True,
            description="Append staged MCP App resources to the user message before the model is called.",
        )
        max_resources: int = Field(
            default=20, description="Maximum resources to append per turn."
        )

    def __init__(self):
        self.valves = self.Valves()

    async def _get_blocks(
        self,
        __event_call__: Optional[Callable[[dict], Awaitable[Any]]] = None,
    ) -> list:
       
        # Pull (and clear) the queued resources from the user's browser tab.
        try:
            raw = await __event_call__(
                {"type": "execute", "data": {"code": _READ_AND_CLEAR_JS}}
            )
        except Exception as e:
            log.debug(f"resource-context: event_call failed: {e}")
            return []

        # event_caller returns {'error': ...} on disconnect/timeout; ignore.
        if not isinstance(raw, str) or not raw.strip():
            return []
        try:
            blocks = json.loads(raw)
        except Exception:
            return []
        if not isinstance(blocks, list) or not blocks:
            return []
        
        return blocks
    
    def _to_content_blocks(self, blocks: list) -> list:
        new_blocks = []
        for block in blocks[: max(0, self.valves.max_resources)]:
            if not isinstance(block, dict):
                continue
            try:
                name, text = _resource_to_text(block)
            except Exception:
                continue
            if not text:
                continue
            new_blocks.append({"type": "text", "text": f"[{name}]\n{text}"})
        return new_blocks

    async def inlet(
        self,
        body: dict,
        __event_call__: Optional[Callable[[dict], Awaitable[Any]]] = None,
    ) -> dict:
        if not self.valves.enabled or __event_call__ is None:
            return body

        blocks = await self._get_blocks(__event_call__)
        new_blocks = self._to_content_blocks(blocks)
        
        if not new_blocks:
            return body

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

        existing = target.get("content") or ""
        if isinstance(existing, str):
            content_list = [{"type": "text", "text": existing}] if existing else []
        elif isinstance(existing, list):
            content_list = list(existing)
        else:
            content_list = []

        target["content"] = content_list + new_blocks
        return body

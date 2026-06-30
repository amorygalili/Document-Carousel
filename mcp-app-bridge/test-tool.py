"""
title: Test Tool
author: mcp-app-bridge
version: 0.1.0
required_open_webui_version: 0.5.0
description: >
  Debugging tools for Open WebUI. `log_tool_context` dumps the context data
  Open WebUI injects into tool calls (__user__, __tool__, __metadata__,
  __messages__, __files__, etc.) to the user's browser console via an
  `execute` event call. `create_test_file` writes a small file into Open
  WebUI's storage and attaches it to the current message by emitting a
  `chat:message:files` event, to verify file creation and file events.
"""

import json
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field


def _dump(value: Any) -> str:
    """Best-effort json.dumps; falls back to default=str for non-serializable."""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"__unserializable__": str(e)})


class Tools:
    class Valves(BaseModel):
        enabled: bool = Field(
            default=True,
            description="Log injected tool context to the browser console.",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def log_tool_context(
        self,
        __user__: Optional[dict] = None,
        __tool__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __messages__: Optional[list] = None,
        __files__: Optional[list] = None,
        __model__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
        __message_id__: Optional[str] = None,
        __session_id__: Optional[str] = None,
        __id__: Optional[str] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[Any]]] = None,
        __event_call__: Optional[Callable[[dict], Awaitable[Any]]] = None,
    ) -> str:
        """
        Log the context data Open WebUI passes into this tool (the user, tool,
        metadata, messages, files, and model) to the browser console. Call this
        to inspect what information is available to tools at runtime.
        :return: A short confirmation string.
        """
        if not self.valves.enabled:
            return "Test tool context logging is disabled."

        if __event_call__ is None:
            return "No __event_call__ available; cannot reach the browser console."

        # Serialize each injected value with json.dumps. __request__ and the
        # event callables are not JSON-serializable, so they fall back to str.
        payload = {
            "__user__": _dump(__user__),
            "__tool__": _dump(__tool__),
            "__metadata__": _dump(__metadata__),
            "__messages__": _dump(__messages__),
            "__files__": _dump(__files__),
            "__model__": _dump(__model__),
            "__chat_id__": _dump(__chat_id__),
            "__message_id__": _dump(__message_id__),
            "__session_id__": _dump(__session_id__),
            "__id__": _dump(__id__),
            "__request__": _dump(str(__request__)),
        }

        # Build JS that console.log's each value in the user's browser tab. Each
        # serialized dump is embedded as a JS string literal via json.dumps so
        # quotes/newlines are escaped safely, then JSON.parse'd back into an
        # object for readable, expandable console output.
        lines = ["console.groupCollapsed('[test-tool] tool context');"]
        for name, dump in payload.items():
            lines.append(
                "try { console.log(%s, JSON.parse(%s)); }"
                "catch (e) { console.log(%s, %s); }"
                % (
                    json.dumps(name),
                    json.dumps(dump),
                    json.dumps(name),
                    json.dumps(dump),
                )
            )
        lines.append("console.groupEnd();")
        lines.append("return 'logged';")
        code = "".join(lines)

        try:
            await __event_call__({"type": "execute", "data": {"code": code}})
        except Exception as e:
            return f"Failed to log tool context to the browser console: {e}"

        return "Logged tool context to the browser console (open devtools)."

    async def create_test_file(
        self,
        filename: str = "test-tool-output.txt",
        content: str = "Hello from test-tool!",
        __request__: Any = None,
        __user__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
        __message_id__: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[Any]]] = None,
    ) -> str:
        """
        Create a small text file in Open WebUI's storage and attach it to the
        current chat message so it shows up in the UI. Use this to test file
        creation and file event emission.
        :param filename: Name for the file to create.
        :param content: Text content to write into the file.
        :return: A JSON status string describing the created file.
        """
        import io

        if __request__ is None:
            return json.dumps({"error": "Request context not available"})
        if not __user__ or not __user__.get("id"):
            return json.dumps({"error": "User context not available"})

        try:
            from fastapi import UploadFile

            from open_webui.models.chats import Chats
            from open_webui.models.users import Users
            from open_webui.routers.files import upload_file_handler

            user = await Users.get_user_by_id(__user__["id"])

            upload = UploadFile(
                file=io.BytesIO(content.encode("utf-8")),
                filename=filename,
                headers={"content-type": "text/plain"},
            )

            # process=False stores the file and creates its DB record without
            # running the RAG/text-extraction pipeline.
            file_item = await upload_file_handler(
                __request__,
                file=upload,
                metadata={},
                process=False,
                user=user,
            )

            file_id = file_item.id
            url = __request__.app.url_path_for("get_file_content_by_id", id=file_id)

            # File entry for the chat message; Chats.add_message_files... returns
            # the normalized list the frontend expects.
            files = [
                {
                    "type": "file",
                    "file": file_item.model_dump(),
                    "id": file_id,
                    "url": url,
                    "name": filename,
                    "collection_name": "",
                    "status": "uploaded",
                }
            ]

            if __chat_id__ and __message_id__:
                db_files = await Chats.add_message_files_by_id_and_message_id(
                    __chat_id__,
                    __message_id__,
                    files,
                )
                if db_files is not None:
                    files = db_files

            # Emit the file event so the UI attaches the file to the message.
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "chat:message:files",
                        "data": {"files": files},
                    }
                )

            return json.dumps(
                {
                    "status": "success",
                    "message": "File created and attached to the message.",
                    "file_id": file_id,
                    "filename": filename,
                    "url": url,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})
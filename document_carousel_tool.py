"""
title: Document Carousel
author: document-carousel
description: Displays an interactive carousel of documents fetched from a Qdrant vector database using RAG.
version: 4.0.0
requirements: httpx
"""

import asyncio
import json
import time
import uuid

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        server_url: str = Field(
            default="http://host.docker.internal:4173",
            description=(
                "Base URL of the HTTP server hosting the built carousel app "
                "(e.g. 'http://localhost:4173' when using `vite preview`)."
            ),
        )
        retrieval_url: str = Field(
            default="http://host.docker.internal:8000",
            description="Base URL of the retrieval server (see retrieval_server.py).",
        )
        qdrant_url: str = Field(
            default="http://host.docker.internal:6333",
            description="URL of the Qdrant server.",
        )
        qdrant_collection: str = Field(
            default="documents",
            description="Name of the Qdrant collection to search.",
        )
        embeddings_base_url: str = Field(
            default="http://host.docker.internal:11434/v1",
            description=(
                "Base URL for the OpenAI-compatible embeddings API "
                "(e.g. Ollama at http://host.docker.internal:11434/v1)."
            ),
        )
        embeddings_api_key: str = Field(
            default="ollama",
            description="API key for the embeddings service (use any non-empty string for Ollama).",
        )
        embeddings_model: str = Field(
            default="nomic-embed-text",
            description="Name of the embeddings model to use.",
        )
        top_k: int = Field(
            default=9,
            description="Number of documents to retrieve from the vector database.",
        )
        selection_timeout: float = Field(
            default=300.0,
            description="Seconds to wait for the user to select documents before giving up.",
        )
        poll_interval: float = Field(
            default=0.75,
            description="Seconds between checks for the user's carousel selection.",
        )
        max_document_chars: int = Field(
            default=0,
            description="Maximum characters of content returned per document (0 = no limit).",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def _retrieve_documents(self, search_query: str) -> list[dict]:
        """
        Calls the retrieval server to embed search_query and return the top-k
        most relevant documents from the configured Qdrant collection.

        Returns a list of carousel document dicts with keys: id, name, description, type, content.
        """
        retrieval_url = self.valves.retrieval_url.rstrip("/")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{retrieval_url}/retrieve",
                json={
                    "search_query": search_query,
                    "qdrant_url": self.valves.qdrant_url,
                    "qdrant_collection": self.valves.qdrant_collection,
                    "embeddings_base_url": self.valves.embeddings_base_url,
                    "embeddings_api_key": self.valves.embeddings_api_key,
                    "embeddings_model": self.valves.embeddings_model,
                    "top_k": self.valves.top_k,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def show_document_carousel(
        self, search_query: str, __event_emitter__=None, __event_call__=None
    ) -> str:
        """
        Searches the vector database for documents relevant to the query, shows an
        interactive carousel, and waits for the user to select documents. The full
        content of the selected documents is returned so the model can use it as
        context for its reply.

        :param search_query: Natural-language query used to retrieve relevant documents.
        """
        server_url = self.valves.server_url.rstrip("/")

        try:
            documents = await self._retrieve_documents(search_query)
        except Exception as exc:
            return json.dumps(
                {"status": "error", "message": f"RAG retrieval error: {exc}"},
                ensure_ascii=False,
            )

        # Assign stable per-run ids and keep the full document (incl. content)
        # server-side; only display fields are sent to the browser.
        docs_by_id: dict[str, dict] = {}
        display_docs: list[dict] = []
        for i, doc in enumerate(documents):
            doc_id = str(i)
            docs_by_id[doc_id] = doc
            display_docs.append(
                {
                    "id": doc_id,
                    "name": doc.get("name", f"Document {i + 1}"),
                    "description": doc.get("description", ""),
                    "type": doc.get("type", ""),
                }
            )

        request_id = uuid.uuid4().hex
        documents_json = json.dumps(display_docs, ensure_ascii=False)

        # Hand the document list and a fresh request id to the carousel and clear
        # any stale selection. The carousel reads these from localStorage and
        # writes the selection back (allowSameOrigin required).
        setup_code = (
            f"localStorage.setItem('carousel:documents', {repr(documents_json)});"
            f"localStorage.setItem('carousel:request_id', {repr(request_id)});"
            f"localStorage.removeItem('carousel:selection');"
        )
        await self._execute(setup_code, __event_call__, __event_emitter__)

        html_content, has_error = await self._fetch_carousel_html(server_url)
        if has_error:
            return json.dumps(
                {"status": "error", "message": html_content}, ensure_ascii=False
            )

        # Render the carousel as a persisted embed so this call can keep running
        # and wait for the user's selection.
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "embeds",
                    "data": {"embeds": [html_content], "replace": False},
                }
            )

        if not __event_call__:
            return json.dumps(
                {
                    "status": "displayed",
                    "message": (
                        "The document carousel was displayed but interactive "
                        "selection is unavailable in this environment."
                    ),
                    "available_documents": [d["name"] for d in display_docs],
                },
                ensure_ascii=False,
            )

        selected_ids = await self._wait_for_selection(request_id, __event_call__)

        # Clear the selection so it does not leak into a later run.
        await self._execute(
            "localStorage.removeItem('carousel:selection');",
            __event_call__,
            __event_emitter__,
        )

        if not selected_ids:
            return json.dumps(
                {
                    "status": "timeout",
                    "message": "No documents were selected before the carousel timed out.",
                },
                ensure_ascii=False,
            )

        result_docs = []
        for doc_id in selected_ids:
            doc = docs_by_id.get(doc_id)
            if not doc:
                continue
            content = doc.get("content") or ""
            cap = self.valves.max_document_chars
            if cap and len(content) > cap:
                content = content[:cap]
            result_docs.append(
                {
                    "name": doc.get("name", ""),
                    "type": doc.get("type", ""),
                    "content": content,
                }
            )

        return json.dumps(
            {
                "status": "success",
                "message": (
                    "The user selected the following documents. Use their content "
                    "as context to answer the user's request."
                ),
                "documents": result_docs,
            },
            ensure_ascii=False,
        )

    async def _execute(self, code: str, __event_call__=None, __event_emitter__=None):
        """
        Runs JS in the browser via the execute event. Prefers the request/response
        caller (__event_call__) so the return value is available; falls back to the
        fire-and-forget emitter for code that returns nothing.
        """
        if __event_call__:
            return await __event_call__({"type": "execute", "data": {"code": code}})
        if __event_emitter__:
            await __event_emitter__({"type": "execute", "data": {"code": code}})
        return None

    async def _wait_for_selection(self, request_id: str, __event_call__) -> list[str]:
        """
        Polls localStorage until the carousel writes a selection matching
        request_id, or until selection_timeout elapses.

        Returns the list of selected document ids (empty on timeout/disconnect).
        """
        read_code = "return localStorage.getItem('carousel:selection');"
        deadline = time.monotonic() + self.valves.selection_timeout
        while time.monotonic() < deadline:
            result = await __event_call__(
                {"type": "execute", "data": {"code": read_code}}
            )
            if isinstance(result, dict) and result.get("error"):
                break
            if result:
                try:
                    payload = json.loads(result)
                except (TypeError, json.JSONDecodeError):
                    payload = None
                if payload and payload.get("requestId") == request_id:
                    return payload.get("ids", []) or []
            await asyncio.sleep(self.valves.poll_interval)
        return []

    async def _fetch_carousel_html(self, server_url: str) -> tuple[str, bool]:
        """
        Fetches index.html from the carousel HTTP server and injects a <base> tag
        so relative asset paths resolve correctly.

        Returns (html_content, has_error). On failure html_content is an error page
        and has_error is True.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(server_url, timeout=10.0)
                response.raise_for_status()
                html_content = response.text
        except Exception as exc:
            error_html = f"""<!DOCTYPE html>
<html><body style="font-family:system-ui;padding:1rem;color:#c00">
  <p><strong>Document Carousel error:</strong> Could not reach the carousel server at
  <code>{server_url}</code>.</p>
  <p>Details: {exc}</p>
  <p>Make sure the carousel app is built (<code>npm run build</code>) and the preview
  server is running (<code>npm run preview</code>).</p>
</body></html>"""
            return error_html, True

        # Inject only a <base> tag so relative asset paths resolve to the server.
        injection = f'<base href="{server_url}/">'

        if "<head>" in html_content:
            html_content = html_content.replace("<head>", f"<head>\n    {injection}", 1)
        else:
            html_content = f"<head>\n    {injection}\n</head>\n" + html_content

        return html_content, False

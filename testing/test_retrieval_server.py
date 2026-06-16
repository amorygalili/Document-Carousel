"""
Manual test script for retrieval_server.py.

Configuration is read from testing/.env, then overridden by CLI flags.

Usage:
    python test_retrieval_server.py "your search query"
    python test_retrieval_server.py "your search query" --top-k 3
    python test_retrieval_server.py "your search query" --server-url http://localhost:8000
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def _load_dotenv(path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ (skips already-set vars)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> None:
    _load_dotenv(Path(__file__).parent / ".env")

    e = os.environ.get
    parser = argparse.ArgumentParser(
        description="Test the document carousel retrieval server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("query", help="Search query to send to the retrieval server.")
    parser.add_argument("--server-url", default=e("RETRIEVAL_SERVER_URL", "http://localhost:8000"), help="Retrieval server base URL.")
    parser.add_argument("--qdrant-url", default=e("QDRANT_URL", "http://host.docker.internal:6333"), help="Qdrant server URL.")
    parser.add_argument("--qdrant-collection", default=e("QDRANT_COLLECTION", "documents"), help="Qdrant collection name.")
    parser.add_argument("--embeddings-base-url", default=e("EMBEDDINGS_BASE_URL", "http://localhost:11434/v1"), help="Embeddings API base URL.")
    parser.add_argument("--embeddings-api-key", default=e("EMBEDDINGS_API_KEY", "ollama"), help="Embeddings API key.")
    parser.add_argument("--embeddings-model", default=e("EMBEDDINGS_MODEL", "nomic-embed-text"), help="Embeddings model name.")
    parser.add_argument("--top-k", type=int, default=int(e("TOP_K", "9")), help="Number of documents to retrieve.")
    args = parser.parse_args()

    url = f"{args.server_url.rstrip('/')}/retrieve"
    payload = {
        "search_query": args.query,
        "qdrant_url": args.qdrant_url,
        "qdrant_collection": args.qdrant_collection,
        "embeddings_base_url": args.embeddings_base_url,
        "embeddings_api_key": args.embeddings_api_key,
        "embeddings_model": args.embeddings_model,
        "top_k": args.top_k,
    }

    print(f"POST {url}")
    print(f"Payload: {json.dumps({**payload, 'embeddings_api_key': '***'}, indent=2)}\n")

    try:
        response = httpx.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
    except httpx.ConnectError:
        print(f"ERROR: Could not connect to {url}. Is the retrieval server running?", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Server returned {e.response.status_code}:\n{e.response.text}", file=sys.stderr)
        sys.exit(1)

    documents = response.json()
    print(f"Retrieved {len(documents)} document(s):\n")
    for doc in documents:
        print(f"  [{doc.get('type', '')}] {doc.get('name', '(no name)')}")
        if doc.get("description"):
            print(f"    {doc['description']}")
    print()
    print("Full response:")
    print(json.dumps(documents, indent=2))


if __name__ == "__main__":
    main()

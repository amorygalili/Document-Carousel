"""
Creates a Qdrant collection with sample documents for testing retrieval_server.py.

The collection is sized automatically to match the chosen embeddings model, so
you can use any OpenAI-compatible embeddings API (OpenAI, Nomic, Ollama, etc.).

Configuration is read from testing/.env, then overridden by CLI flags.

Usage:
    python create_test_collection.py
    python create_test_collection.py --collection my-test
    python create_test_collection.py \\
        --embeddings-base-url https://api.openai.com/v1 \\
        --embeddings-api-key sk-... \\
        --embeddings-model text-embedding-3-small
"""

import argparse
import os
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore


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


SAMPLE_DOCUMENTS = [
    Document(
        page_content="Cheddar is a firm, natural cheese originating from the English village of Cheddar in Somerset.",
        metadata={"name": "Cheddar Cheese", "type": "article", "description": "Overview of cheddar cheese."},
    ),
    Document(
        page_content="Brie is a soft cow's milk cheese named after the French region of Brie.",
        metadata={"name": "Brie", "type": "article", "description": "Overview of brie cheese."},
    ),
    Document(
        page_content="Parmesan is a hard, granular cheese produced in the provinces of Parma and Reggio Emilia.",
        metadata={"name": "Parmesan", "type": "article", "description": "Overview of parmesan cheese."},
    ),
    Document(
        page_content="Mozzarella is a traditionally southern Italian cheese made from Italian buffalo milk.",
        metadata={"name": "Mozzarella", "type": "article", "description": "Overview of mozzarella cheese."},
    ),
    Document(
        page_content="Gouda is a mild, yellow cheese made from cow's milk, originating from the Netherlands.",
        metadata={"name": "Gouda", "type": "article", "description": "Overview of gouda cheese."},
    ),
]


def main() -> None:
    _load_dotenv(Path(__file__).parent / ".env")

    e = os.environ.get
    parser = argparse.ArgumentParser(
        description="Create a Qdrant test collection with sample documents.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--qdrant-url", default=e("QDRANT_URL", "http://localhost:6333"), help="Qdrant server URL.")
    parser.add_argument("--collection", default=e("QDRANT_COLLECTION", "documents"), help="Qdrant collection name to create.")
    parser.add_argument("--embeddings-base-url", default=e("EMBEDDINGS_BASE_URL", "http://localhost:11434/v1"), help="Embeddings API base URL.")
    parser.add_argument("--embeddings-api-key", default=e("EMBEDDINGS_API_KEY", "ollama"), help="Embeddings API key.")
    parser.add_argument("--embeddings-model", default=e("EMBEDDINGS_MODEL", "nomic-embed-text"), help="Embeddings model name.")
    args = parser.parse_args()

    print(f"Embeddings model : {args.embeddings_model} ({args.embeddings_base_url})")
    print(f"Qdrant           : {args.qdrant_url}")
    print(f"Collection       : {args.collection}")
    print(f"Documents        : {len(SAMPLE_DOCUMENTS)}")
    print()

    embeddings = OpenAIEmbeddings(
        base_url=args.embeddings_base_url,
        api_key=args.embeddings_api_key,
        model=args.embeddings_model,
    )

    try:
        QdrantVectorStore.from_documents(
            documents=SAMPLE_DOCUMENTS,
            embedding=embeddings,
            url=args.qdrant_url,
            collection_name=args.collection,
            force_recreate=True,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Collection '{args.collection}' created with {len(SAMPLE_DOCUMENTS)} documents.")
    print("Test it with:")
    print(f"  python test_retrieval_server.py cheese --qdrant-collection {args.collection}")


if __name__ == "__main__":
    main()

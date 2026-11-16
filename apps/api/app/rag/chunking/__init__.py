from typing import Any

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def chunk(documents: list[Document]) -> list[tuple[str, dict[str, Any]]]:
    """Non-empty chunk texts, each with a copy of its document's metadata."""
    return [
        (text, dict(document.metadata))
        for document in documents
        for text in _splitter.split_text(document.text)
        if text.strip()
    ]

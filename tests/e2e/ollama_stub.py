"""Stdlib stand-in for Ollama, so the e2e stack needs no model and no paid API.

Serves the two endpoints the API calls: `/api/embed` (deterministic, non-zero vectors)
and `/api/chat` (the corrective-RAG grader when `format` is set, else a fixed answer).
"""

import hashlib
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = 11435
EMBED_DIM = 8
ANSWER = "Uploads are stored in object storage."
GRADE = {"relevant": [0]}


def embed_text(text: str) -> list[float]:
    # Bytes 1..256 shifted to 1.0..2.0: never zero, so pgvector cosine stays defined.
    digest = hashlib.sha256(text.encode()).digest()
    return [1 + byte / 255 for byte in digest[:EMBED_DIM]]


def chat_chunks(request: dict[str, Any]) -> Iterator[dict[str, Any]]:
    content = json.dumps(GRADE) if request.get("format") else ANSWER
    yield {
        "model": request["model"],
        "message": {"role": "assistant", "content": content},
        "done": False,
    }
    yield {
        "model": request["model"],
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
    }


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            inputs = request["input"]
            if isinstance(inputs, str):
                inputs = [inputs]
            self._send(
                "application/json",
                json.dumps(
                    {"model": request["model"], "embeddings": [embed_text(t) for t in inputs]}
                ),
            )
        elif self.path == "/api/chat":
            body = "".join(json.dumps(chunk) + "\n" for chunk in chat_chunks(request))
            self._send("application/x-ndjson", body)
        else:
            self._not_found()

    def do_GET(self) -> None:
        self._not_found()

    def _send(self, content_type: str, body: str) -> None:
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _not_found(self) -> None:
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep pytest output clean; the stub only matters when a call fails


def start() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

"""Exercise real local inference with networking blocked, then API degradation.

Run after search_tools migrate/seed. Emits reviewable C-module evidence.
"""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.main import app, get_embedding_backend
from services.common.config import Settings, get_settings
from services.common.db import get_db, make_engine, make_session_factory
from services.search.embeddings import LocalPplxEmbeddingBackend
from services.search.evaluation import evaluate_queries
from services.search.text import MODEL_DIRECTORY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///work/search-demo.db")
    parser.add_argument("--model-path", default=MODEL_DIRECTORY)
    parser.add_argument("--output", type=Path, default=Path("work/offline-check.json"))
    args = parser.parse_args()
    gold = json.loads(Path("fixtures/search/gold-queries.json").read_text(encoding="utf-8"))
    engine = make_engine(args.database_url)
    backend = LocalPplxEmbeddingBackend(args.model_path)
    settings = Settings(_env_file=None)
    try:
        with make_session_factory(engine)() as db:
            original_connect = socket.socket.connect
            original_connect_ex = socket.socket.connect_ex
            original_create_connection = socket.create_connection

            def check_address(address):
                # Windows asyncio uses a loopback socket pair for its event loop.
                # Block external traffic while allowing that OS mechanism.
                if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                    raise AssertionError("Local model attempted an external network connection")

            def connect(sock, address):
                check_address(address)
                return original_connect(sock, address)

            def connect_ex(sock, address):
                check_address(address)
                return original_connect_ex(sock, address)

            def create_connection(address, *args, **kwargs):
                check_address(address)
                return original_create_connection(address, *args, **kwargs)

            with (
                patch.object(socket.socket, "connect", connect),
                patch.object(socket.socket, "connect_ex", connect_ex),
                patch.object(socket, "create_connection", create_connection),
            ):
                offline = evaluate_queries(db, gold, settings, backend)
                app.dependency_overrides[get_db] = lambda: db
                app.dependency_overrides[get_embedding_backend] = lambda: backend
                hybrid = []
                with TestClient(app) as client:
                    for query in gold["queries"]:
                        response = client.post("/search", json={"query": query["query"]})
                        assert response.status_code == 200
                        data = response.json()
                        assert data["effective_mode"] == "hybrid" and not data["degraded"]
                        assert len({hit["file_id"] for hit in data["results"]}) == len(
                            data["results"]
                        )
                        hybrid.append({"id": query["id"], "response": data})
                    app.dependency_overrides[get_settings] = lambda: Settings(
                        embedding_enabled=False,
                        _env_file=None,
                    )
                    degradation = []
                    for query in gold["queries"][:5]:
                        data = client.post("/search", json={"query": query["query"]}).json()
                        assert data["effective_mode"] == "keyword" and data["degraded"]
                        assert data["results"][0]["file_id"] == query["expected_file_id"]
                        degradation.append({"id": query["id"], "response": data})
            report = {
                "external_network_blocked": True,
                "loopback_allowed": True,
                "offline_evaluation": offline,
                "hybrid_queries": hybrid,
                "disabled_ai_queries": degradation,
                "summary": {
                    **offline["summary"],
                    "hybrid_http_200": len(hybrid),
                    "disabled_ai_keyword_passed": len(degradation),
                },
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(report["summary"], indent=2))
            if not offline["passed"]:
                raise SystemExit(1)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    main()

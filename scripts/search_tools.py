"""CMD-friendly local utilities for member C; no Git operations."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from alembic import command
from alembic.config import Config

from services.common.config import Settings
from services.common.db import make_engine, make_session_factory
from services.search.embeddings import HTTPEmbeddingBackend, LocalE5EmbeddingBackend
from services.search.indexing import embed_version, index_document
from services.search.text import MODEL_FILES, MODEL_ID, MODEL_NAME, MODEL_REVISION

REPO = Path(__file__).resolve().parents[1]


def prepare_model(destination: Path) -> None:
    """Only this explicit preparation command can download model files."""
    from huggingface_hub import snapshot_download

    filenames = list(MODEL_FILES)
    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=str(destination),
        allow_patterns=filenames,
        max_workers=3,
    )
    checksums = {}
    for filename in filenames:
        with (destination / filename).open("rb") as stream:
            checksums[filename] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": checksums}
    (destination / "model-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared local model: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["download-model", "migrate", "seed", "index", "evaluate"]
    )
    parser.add_argument("--database-url", default="sqlite:///work/search-demo.db")
    parser.add_argument("--model-path", type=Path, default=REPO / "models/multilingual-e5-small")
    parser.add_argument("--fixture", type=Path, default=REPO / "fixtures/search/mock-chunks.json")
    parser.add_argument("--gold", type=Path, default=REPO / "fixtures/search/gold-queries.json")
    parser.add_argument("--backend", choices=["local", "http", "off"], default="local")
    parser.add_argument("--ai-url", default="http://127.0.0.1:8100")
    parser.add_argument("--version-id", help="Required by the index worker handler command")
    parser.add_argument("--output", type=Path, default=REPO / "work/search-evaluation.json")
    args = parser.parse_args()
    if args.action == "download-model":
        prepare_model(args.model_path)
        return
    (REPO / "work").mkdir(exist_ok=True)
    if args.action == "migrate":
        config = Config(str(REPO / "alembic.ini"))
        config.attributes["database_url"] = args.database_url
        command.upgrade(config, "head")
        return
    backend = None
    if args.backend == "local":
        backend = LocalE5EmbeddingBackend(str(args.model_path))
    elif args.backend == "http":
        backend = HTTPEmbeddingBackend(args.ai_url)
    engine = make_engine(args.database_url)
    try:
        with make_session_factory(engine)() as db:
            if args.action == "seed":
                fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
                embedding_errors = []
                for document in fixture["documents"]:
                    version = index_document(db, **document)
                    if backend is not None:
                        result = embed_version(db, version.id, backend)
                        print(json.dumps(asdict(result)))
                        if result.embedding_error:
                            embedding_errors.append(result.embedding_error)
                db.commit()
                print(f"Seeded {len(fixture['documents'])} synthetic documents")
                if embedding_errors:
                    print(
                        "Text retained, but embedding failed. "
                        "Fix the model/service and re-run seed."
                    )
                    raise SystemExit(1)
            elif args.action == "index":
                if not args.version_id or backend is None:
                    parser.error("index requires --version-id and an embedding backend")
                result = embed_version(db, args.version_id, backend)
                db.commit()
                print(json.dumps(asdict(result), indent=2))
                if result.embedding_error:
                    raise SystemExit(1)
            else:
                from services.search.evaluation import evaluate_queries

                gold = json.loads(args.gold.read_text(encoding="utf-8"))
                settings = Settings(embedding_enabled=backend is not None, _env_file=None)
                report = evaluate_queries(db, gold, settings, backend)
                report["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
                report["gold_sha256"] = hashlib.sha256(args.gold.read_bytes()).hexdigest()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
                print(f"Wrote evaluation: {args.output}")
                if not report["passed"]:
                    raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

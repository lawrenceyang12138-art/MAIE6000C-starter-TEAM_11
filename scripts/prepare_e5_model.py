"""Download the pinned E5 model and write its checksum manifest.

Run only when the team explicitly wants a semantic-search release candidate:

    pip install -e ".[embeddings]"
    python scripts/prepare_e5_model.py

The application itself never downloads a model. The resulting directory is
ignored by Git and must be copied separately to the demo machine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from services.search.text import MODEL_FILES, MODEL_ID, MODEL_NAME, MODEL_REVISION


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("models/multilingual-e5-small"),
    )
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=str(args.destination),
        allow_patterns=list(MODEL_FILES),
        max_workers=3,
    )
    manifest = {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "sha256": {
            filename: sha256(args.destination / filename)
            for filename in MODEL_FILES
        },
    }
    (args.destination / "model-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {MODEL_ID} at {args.destination}")


if __name__ == "__main__":
    main()

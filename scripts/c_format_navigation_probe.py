"""Read-only probe, piped to the *candidate API container*, not a semantic search test."""

import json
from collections import Counter
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.models import FileRecord, FileVersion, SourceChunk
from services.common.schemas import SearchMode
from services.search.navigation_runtime import PageNavigation
from services.search.page_metadata import load_page_metadata


def inspect_root(root):
    settings = get_settings()
    nav = PageNavigation("page 3", settings.search_page_navigation_enabled, SearchMode.HYBRID)
    db = create_engine(settings.database_url).execution_options(postgresql_readonly=True)
    probes = {}
    lookups = Counter()

    def count_pdf_reads(frame, event, arg):
        if event == "call" and frame.f_code is load_page_metadata.__code__:
            lookups[version.id] += 1
    with Session(db) as session:
        rows = session.execute(select(SourceChunk, FileVersion, FileRecord)
                               .join(FileVersion, SourceChunk.version_id == FileVersion.id)
                               .join(FileRecord, FileVersion.file_id == FileRecord.id)
                               .where(FileRecord.root_id == root,
                                      FileRecord.current_version_id == FileVersion.id)
                               .order_by(FileRecord.relative_path, SourceChunk.ordinal))
        for chunk, version, file in rows:
            previous = sys.getprofile()
            sys.setprofile(count_pdf_reads)  # Count actual calls; do not replace results.
            try:
                allowed = nav.allows(session, chunk, version, file)
            finally:
                sys.setprofile(previous)
            probes.setdefault(version.id, []).append({"id": chunk.id, "page": chunk.page_number,
                                                      "allowed": allowed})
    db.dispose()
    nav.finish([])
    return {"active": nav.active, "diagnostics": nav.report, "chunks": probes,
            "pdf_metadata_lookups": dict(lookups)}


if __name__ == "__main__":
    print(json.dumps(inspect_root(sys.argv[1]), ensure_ascii=True))

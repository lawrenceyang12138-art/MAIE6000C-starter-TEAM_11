"""Compare durable source/index/review state across the dedicated stack restart."""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

destination = Path('submissions/week07/evidence/20261031-w7/restart.json')
phase = sys.argv[1]
report = json.loads(destination.read_text('utf-8')) if destination.exists() else {}
queries = {
    'roots': 'SELECT * FROM authorized_roots ORDER BY id',
    'files': 'SELECT * FROM files ORDER BY id',
    'versions': 'SELECT * FROM file_versions ORDER BY id',
    'chunks': 'SELECT * FROM source_chunks ORDER BY id',
    'keyword': 'SELECT * FROM chunk_search_index ORDER BY chunk_id',
    'token': '''SELECT chunk_id, model_id, model_revision, token_dimensions,
        token_count, text_sha256 FROM chunk_token_search_index ORDER BY chunk_id''',
    'page': 'SELECT * FROM version_page_search_metadata ORDER BY version_id',
    'entities': 'SELECT * FROM entities ORDER BY id',
    'relations': 'SELECT * FROM relationships ORDER BY id',
    'relation_evidence': '''SELECT * FROM relationship_evidence
        ORDER BY relationship_id,chunk_id,start_offset,end_offset''',
    'reviews': 'SELECT * FROM reviews ORDER BY id',
    'jobs': 'SELECT * FROM jobs ORDER BY id',
}
engine = create_engine(os.environ['W7_DATABASE_URL'])
result = {'at': datetime.now(timezone.utc).isoformat(), 'checks': {}}
try:
    with httpx.Client(base_url='http://127.0.0.1:18081', trust_env=False, timeout=60) as client:
        for _ in range(180):
            try:
                if client.get('/health/ready').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        assert client.get('/health/ready').status_code == 200
        with engine.connect() as db:
            assert db.scalar(text(
                "SELECT count(*) FROM jobs WHERE status IN ('pending','claimed')"
            )) == 0
            tables = {name: [dict(row) for row in db.execute(text(sql)).mappings()]
                      for name, sql in queries.items()}
        result['rows'] = {name: len(rows) for name, rows in tables.items()}
        result['table_sha256'] = {name: hashlib.sha256(json.dumps(rows, sort_keys=True,
            default=str).encode()).hexdigest() for name, rows in tables.items()}
        result['reviews'] = tables['reviews']
        result['evidence'] = {}
        for chunk_id in ('45718fbe-cded-463f-8542-3ea22866d83b',
                         '877344b9-44f6-4988-a683-1e0dda590b7a',
                         '9d3f0668-0897-4712-8c65-1b27d5219d6b'):
            response = client.get('/evidence/' + chunk_id)
            assert response.status_code == 200
            result['evidence'][chunk_id] = response.json()
        result['checks']['queue_settled_and_three_recorded_sources_readable'] = True
        if phase == 'after':
            assert result['rows'] == report['before']['rows']
            assert result['table_sha256'] == report['before']['table_sha256']
            assert result['evidence'] == report['before']['evidence']
            result['checks']['all_durable_tables_unchanged_after_container_recreation'] = True
        result['passed'] = True
except Exception as exc:
    result['passed'] = False
    result['error_type'] = type(exc).__name__
    raise
finally:
    report[phase] = result
    report['passed'] = (
        report.get('before', {}).get('passed') and report.get('after', {}).get('passed')
    )
    destination.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    engine.dispose()
print(json.dumps({'phase': phase, 'passed': result['passed'], 'rows': result['rows']}))

"""Record real model modes and AI disconnection on the dedicated W7 stack."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

phase = sys.argv[1]
destination = Path('submissions/week07/evidence/20261031-w7/model-modes.json')
report = json.loads(destination.read_text('utf-8')) if destination.exists() else {}
result = {'at': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'responses': {}}
root = 'fdf4ab46-b7ea-4bff-96bd-6fd496272134'
engine = create_engine('postgresql+psycopg://postgres:postgres@127.0.0.1:15481/maie6000c')
try:
    with httpx.Client(base_url='http://127.0.0.1:18081', trust_env=False, timeout=60) as client:
        setup = client.get('/setup').json()
        result['setup'] = setup
        for mode in ('keyword', 'semantic', 'hybrid'):
            response = client.post('/search', json={
                'query': 'invoices refunds', 'root_id': root, 'mode': mode, 'top_k': 3,
            })
            assert response.status_code == 200
            data = response.json()
            result['responses'][mode] = data
            assert data['results']
            hit = data['results'][0]
            assert hit['file_path'] == 'regression/group-a/doc01.pdf'
            evidence = client.get('/evidence/' + hit['chunk_id'])
            assert evidence.status_code == 200
            assert evidence.json()['version_id'] == hit['version_id']
            assert evidence.json()['page_number'] == hit['page']
            if phase == 'disconnected' and mode != 'keyword':
                assert data['effective_mode'] == 'keyword' and data['degraded'] is True
                assert data['degradation_reason'] in ('ai_unavailable', 'ai_timeout')
            else:
                assert data['effective_mode'] == mode and data['degraded'] is False
                if mode != 'keyword':
                    assert data['embedding_dimensions'] == 128
                    assert data['embedding_model'] == setup['model']
                    assert hit['semantic_score'] is not None
            result['checks'][mode + '_correct_mode_and_source'] = True
        assert client.get('/health/ready').status_code == 200
        result['checks']['api_remains_ready'] = True
        with engine.connect() as db:
            count = db.scalar(text('''SELECT count(*) FROM chunk_token_search_index t
                JOIN source_chunks c ON c.id=t.chunk_id JOIN file_versions v ON v.id=c.version_id
                JOIN files f ON f.current_version_id=v.id WHERE f.root_id=:root'''), {'root': root})
            result['canonical_token_index_count'] = count
            assert count == 30
            result['checks']['all_30_original_chunks_automatically_received_vectors'] = True
        result['passed'] = True
except Exception as exc:
    result['passed'] = False
    result['error_type'] = type(exc).__name__
    raise
finally:
    report[phase] = result
    report['passed'] = bool(report) and all(r.get('passed', False) for r in report.values()
                                           if isinstance(r, dict))
    destination.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    engine.dispose()
print(json.dumps({'phase': phase, 'passed': result['passed'], 'checks': result['checks']}))

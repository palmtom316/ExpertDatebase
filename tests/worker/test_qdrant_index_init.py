import sys
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / 'services' / 'worker'
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.qdrant_index import DEFAULT_PAYLOAD_INDEXES, ensure_payload_indexes


@patch('worker.qdrant_index.requests.put')
def test_ensure_payload_indexes_posts_index_requests(m_put: Mock) -> None:
    resp = Mock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    m_put.return_value = resp

    out = ensure_payload_indexes(endpoint='http://qdrant:6333', collection='chunks_v1')

    assert out['created'] >= 2
    assert m_put.call_count >= 2
    first_call = m_put.call_args_list[0]
    assert '/collections/chunks_v1/index' in first_call.kwargs['url']
    assert any(spec.get("field_name") == "clause_id" for spec in DEFAULT_PAYLOAD_INDEXES)
    assert any(spec.get("field_name") == "is_mandatory" and spec.get("field_schema") == "bool" for spec in DEFAULT_PAYLOAD_INDEXES)
    assert any(spec.get("field_name") == "table_repr" and spec.get("field_schema") == "keyword" for spec in DEFAULT_PAYLOAD_INDEXES)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / 'services' / 'api-server'
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.llm_log_repo import InMemoryLLMLogRepo
from app.services.llm_router import LLMRouter


def test_llm_router_persists_log_to_repo() -> None:
    repo = InMemoryLLMLogRepo()
    router = LLMRouter(log_repo=repo)

    router.route_and_generate(task_type='qa_generate', prompt='测试问题')

    assert len(repo.logs) == 1
    assert repo.logs[0]['task_type'] == 'qa_generate'
    assert repo.logs[0]['provider']

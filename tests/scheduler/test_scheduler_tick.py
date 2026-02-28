import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SERVICE = ROOT / "services" / "scheduler"
if str(SCHEDULER_SERVICE) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SERVICE))

from scheduler.main import Scheduler, SchedulerConfig


def test_scheduler_tick_triggers_both_jobs(monkeypatch):
    calls = []

    def fake_post(self, path, payload=None):
        calls.append((path, payload))

    monkeypatch.setattr(Scheduler, "_post", fake_post)
    s = Scheduler(SchedulerConfig(api_base="http://api:8080", expiry_interval_s=1, eval_interval_s=1))

    fired = s.tick(now=100.0)

    assert fired["expiry_scan"] is True
    assert fired["eval_schedule"] is True
    assert any(x[0] == "/api/admin/jobs/cleanup-failed" for x in calls)
    assert any(x[0] == "/api/admin/eval/runs/start" for x in calls)

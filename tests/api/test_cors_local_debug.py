import importlib
import sys
from pathlib import Path

from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))


def test_cors_allows_local_frontend_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5500")

    import app.main as app_main

    app_main = importlib.reload(app_main)
    cors_layers = [layer for layer in app_main.app.user_middleware if layer.cls is CORSMiddleware]
    assert cors_layers
    assert "http://localhost:5500" in cors_layers[0].kwargs.get("allow_origins", [])

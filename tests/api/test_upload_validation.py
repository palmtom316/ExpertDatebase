import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.api.upload import validate_upload_payload  # noqa: E402


def test_validate_upload_rejects_non_pdf() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_upload_payload(filename="hello.txt", content_type="text/plain", content=b"abc")
    assert exc.value.status_code == 415


def test_validate_upload_rejects_oversized_file() -> None:
    old = dict(os.environ)
    os.environ["UPLOAD_MAX_MB"] = "0.0001"
    try:
        with pytest.raises(HTTPException) as exc:
            validate_upload_payload(
                filename="a.pdf",
                content_type="application/pdf",
                content=b"0" * 1024,
            )
        assert exc.value.status_code == 413
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_validate_upload_accepts_pdf() -> None:
    validate_upload_payload(
        filename="ok.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4",
    )

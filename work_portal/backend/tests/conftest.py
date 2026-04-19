import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.storage import Storage  # noqa: E402


class FakeSummarizer:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {
            "summary": "Fake summary.",
            "action_items": [{"owner": "Chris", "task": "Do the thing", "due": "2026-05-01"}],
            "files": [{"name": "Thing.xlsx", "note": "For review"}],
        }
        self.calls: list[dict[str, Any]] = []

    def summarize(self, transcript: str, title: str = "L10 Meeting") -> dict[str, Any]:
        self.calls.append({"transcript": transcript, "title": title})
        return self.payload


class FakeHttpResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class FakeHttpClient:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, headers: dict[str, str], params: dict[str, Any]) -> FakeHttpResponse:
        self.calls.append({"url": url, "headers": headers, "params": params})
        return FakeHttpResponse(self.payload, self.status_code)


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    (data_dir / "meetings").mkdir(parents=True, exist_ok=True)
    return Config(
        data_dir=data_dir,
        secret_key="test-secret",
        api_key="test-key",
        anthropic_api_key="fake-anthropic",
        readai_api_key="fake-readai",
    )


@pytest.fixture
def storage(tmp_config: Config) -> Storage:
    return Storage(data_dir=tmp_config.data_dir)


@pytest.fixture
def client(tmp_config: Config):
    app = create_app(tmp_config)
    app.config["SUMMARIZER"] = FakeSummarizer()
    with app.test_client() as c:
        yield c


@pytest.fixture
def fake_summarizer() -> FakeSummarizer:
    return FakeSummarizer()

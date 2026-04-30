import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data_dir: Path
    secret_key: str
    api_key: str
    anthropic_api_key: str
    readai_api_key: str
    database_url: str = ""
    readai_base_url: str = "https://api.read.ai/v1"
    summarizer_model: str = "claude-haiku-4-5-20251001"
    # Match the LV Executive call titles only — NOT generic "LV Construction"
    # mentions in unrelated meeting titles (e.g. "Weekly OAC Meeting: BBC, Six
    # Peak, LV Construction, AERO, ..." should be ignored).
    ingest_title_pattern: str = r"(?i)\bLV\s+Exec(?:utive)?\b|\bBi-?Weekly\s+LV\b"

    @classmethod
    def from_env(cls) -> "Config":
        backend_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(os.environ.get("LV_DATA_DIR", backend_dir / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "meetings").mkdir(parents=True, exist_ok=True)
        return cls(
            data_dir=data_dir,
            secret_key=os.environ.get("APP_SECRET_KEY", "dev-only-not-for-production"),
            api_key=os.environ.get("PORTAL_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            readai_api_key=os.environ.get("READAI_API_KEY", ""),
            database_url=os.environ.get("DATABASE_URL", ""),
            readai_base_url=os.environ.get("READAI_BASE_URL", "https://api.read.ai/v1"),
            summarizer_model=os.environ.get("SUMMARIZER_MODEL", "claude-haiku-4-5-20251001"),
            ingest_title_pattern=os.environ.get(
                "INGEST_TITLE_PATTERN",
                r"(?i)LV\s*(Construction|Exec)|Executive|Bi-?Weekly LV",
            ),
        )

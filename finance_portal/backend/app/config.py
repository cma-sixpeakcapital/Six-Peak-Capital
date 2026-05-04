import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    ingest_title_pattern: str = r"(?i)Six Peak.*Finance|Monthly Finance|SP Finance"
    # Follow-up email job — see app/jobs/send_followups.py
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_calendar_id: str = "primary"
    followup_sender_email: str = ""
    followup_cal_event_id: str = ""
    followup_subject_prefix: str = "Finance Follow-up"
    followup_portal_name: str = "Six Peak Monthly Finance"
    followup_portal_url: str = "https://finance.sixpeakapps.com"
    followup_cadence: str = "monthly"
    followup_min_age_hours: int = 24
    followup_max_age_days: int = 7
    followup_dry_run: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        backend_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(os.environ.get("FINANCE_DATA_DIR", backend_dir / "data"))
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
                r"(?i)Six Peak.*Finance|Monthly Finance|SP Finance",
            ),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            google_refresh_token=os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
            google_calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
            followup_sender_email=os.environ.get("FOLLOWUP_SENDER_EMAIL", ""),
            followup_cal_event_id=os.environ.get("FOLLOWUP_CAL_EVENT_ID", ""),
            followup_subject_prefix=os.environ.get("FOLLOWUP_SUBJECT_PREFIX", "Finance Follow-up"),
            followup_portal_name=os.environ.get("FOLLOWUP_PORTAL_NAME", "Six Peak Monthly Finance"),
            followup_portal_url=os.environ.get("FOLLOWUP_PORTAL_URL", "https://finance.sixpeakapps.com"),
            followup_cadence=os.environ.get("FOLLOWUP_CADENCE", "monthly"),
            followup_min_age_hours=int(os.environ.get("FOLLOWUP_MIN_AGE_HOURS", "24")),
            followup_max_age_days=int(os.environ.get("FOLLOWUP_MAX_AGE_DAYS", "7")),
            followup_dry_run=_bool_env("FOLLOWUP_DRY_RUN", True),
        )

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
    ingest_title_pattern: str = r"(?i)\bL10\b|Weekly Six Peak|Level 10|Leadership"
    # Follow-up email job — see app/jobs/send_followups.py
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_calendar_id: str = "primary"
    followup_sender_email: str = ""
    followup_cal_event_id: str = ""
    followup_subject_prefix: str = "L10 Follow-up"
    followup_portal_name: str = "L10 Weekly"
    followup_portal_url: str = "https://l10.sixpeakapps.com"
    followup_cadence: str = "weekly"
    followup_min_age_hours: int = 24
    followup_max_age_days: int = 7
    followup_dry_run: bool = True
    # Mid-cycle reminder job — fires 3 days after each weekly L10 meeting
    # (halfway between meetings). See app/jobs/send_reminders.py.
    followup_reminder_subject_prefix: str = "L10 Check-in"
    followup_reminder_min_age_days: int = 3
    followup_reminder_max_age_days: int = 10
    followup_reminder_dry_run: bool = True

    @classmethod
    def from_env(cls, prefix: str = "") -> "Config":
        # Per-portal env namespacing: in the consolidated single-process
        # deployment all portals share os.environ, so each portal reads its own
        # PREFIXED vars (e.g. L10_PORTAL_API_KEY) and falls back to the bare
        # name for standalone runs and for values shared across portals.
        def env(name: str, default: str = "") -> str:
            return os.environ.get(prefix + name, os.environ.get(name, default))

        def env_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(prefix + name, os.environ.get(name))
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        backend_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(env("DATA_DIR", str(backend_dir / "data")))
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "meetings").mkdir(parents=True, exist_ok=True)
        return cls(
            data_dir=data_dir,
            secret_key=env("APP_SECRET_KEY", "dev-only-not-for-production"),
            api_key=env("PORTAL_API_KEY", ""),
            anthropic_api_key=env("ANTHROPIC_API_KEY", ""),
            readai_api_key=env("READAI_API_KEY", ""),
            database_url=env("DATABASE_URL", ""),
            readai_base_url=env("READAI_BASE_URL", "https://api.read.ai/v1"),
            summarizer_model=env("SUMMARIZER_MODEL", "claude-haiku-4-5-20251001"),
            ingest_title_pattern=env(
                "INGEST_TITLE_PATTERN",
                r"(?i)\bL10\b|Weekly Six Peak|Level 10|Leadership",
            ),
            google_client_id=env("GOOGLE_CLIENT_ID", ""),
            google_client_secret=env("GOOGLE_CLIENT_SECRET", ""),
            google_refresh_token=env("GOOGLE_REFRESH_TOKEN", ""),
            google_calendar_id=env("GOOGLE_CALENDAR_ID", "primary"),
            followup_sender_email=env("FOLLOWUP_SENDER_EMAIL", ""),
            followup_cal_event_id=env("FOLLOWUP_CAL_EVENT_ID", ""),
            followup_subject_prefix=env("FOLLOWUP_SUBJECT_PREFIX", "L10 Follow-up"),
            followup_portal_name=env("FOLLOWUP_PORTAL_NAME", "L10 Weekly"),
            followup_portal_url=env("FOLLOWUP_PORTAL_URL", "https://l10.sixpeakapps.com"),
            followup_cadence=env("FOLLOWUP_CADENCE", "weekly"),
            followup_min_age_hours=int(env("FOLLOWUP_MIN_AGE_HOURS", "24")),
            followup_max_age_days=int(env("FOLLOWUP_MAX_AGE_DAYS", "7")),
            followup_dry_run=env_bool("FOLLOWUP_DRY_RUN", True),
            followup_reminder_subject_prefix=env(
                "FOLLOWUP_REMINDER_SUBJECT_PREFIX", "L10 Check-in"
            ),
            followup_reminder_min_age_days=int(
                env("FOLLOWUP_REMINDER_MIN_AGE_DAYS", "3")
            ),
            followup_reminder_max_age_days=int(
                env("FOLLOWUP_REMINDER_MAX_AGE_DAYS", "10")
            ),
            followup_reminder_dry_run=env_bool("FOLLOWUP_REMINDER_DRY_RUN", True),
        )

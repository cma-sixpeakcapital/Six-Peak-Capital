import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROCKS_SCHEMA_DEFAULT: dict[str, Any] = {
    "team": [],
    "rocks": {},
    "company_rocks": [],
}

STATUSES = {"complete", "incomplete"}


@dataclass
class Storage:
    data_dir: Path

    @property
    def rocks_path(self) -> Path:
        return self.data_dir / "rocks.json"

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

    def load_rocks(self) -> dict[str, Any]:
        if not self.rocks_path.exists():
            return json.loads(json.dumps(ROCKS_SCHEMA_DEFAULT))
        with self.rocks_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save_rocks(self, data: dict[str, Any]) -> None:
        self.rocks_path.parent.mkdir(parents=True, exist_ok=True)
        with self.rocks_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def set_person_rocks(self, person: str, rocks: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.load_rocks()
        for rock in rocks:
            status = rock.get("status", "incomplete")
            if status not in STATUSES:
                raise ValueError(f"invalid status: {status}")
        data.setdefault("rocks", {})[person] = rocks
        people = {p["name"] for p in data.get("team", [])}
        if person not in people:
            data.setdefault("team", []).append({"name": person, "role": ""})
        self.save_rocks(data)
        return data

    def set_company_rocks(self, rocks: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.load_rocks()
        for rock in rocks:
            status = rock.get("status", "incomplete")
            if status not in STATUSES:
                raise ValueError(f"invalid status: {status}")
        data["company_rocks"] = rocks
        self.save_rocks(data)
        return data

    def toggle_rock(self, rock_id: str) -> dict[str, Any] | None:
        """Flip status between complete/incomplete for the rock with this id.

        Searches person rocks first, then company rocks.
        Returns the updated rock, or None if not found.
        """
        data = self.load_rocks()
        for rocks in (data.get("rocks") or {}).values():
            for rock in rocks:
                if rock.get("id") == rock_id:
                    rock["status"] = "incomplete" if rock.get("status") == "complete" else "complete"
                    self.save_rocks(data)
                    return rock
        for rock in data.get("company_rocks") or []:
            if rock.get("id") == rock_id:
                rock["status"] = "incomplete" if rock.get("status") == "complete" else "complete"
                self.save_rocks(data)
                return rock
        return None

    def save_meeting(self, meeting: dict[str, Any]) -> Path:
        if "id" not in meeting or "date" not in meeting:
            raise ValueError("meeting requires 'id' and 'date'")
        self.meetings_dir.mkdir(parents=True, exist_ok=True)
        path = self.meetings_dir / f"{meeting['id']}.json"
        meeting = dict(meeting)
        meeting.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        with path.open("w", encoding="utf-8") as f:
            json.dump(meeting, f, indent=2, sort_keys=True)
        return path

    def list_meetings(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.meetings_dir.exists():
            return []
        meetings: list[dict[str, Any]] = []
        for path in self.meetings_dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as f:
                meetings.append(json.load(f))
        meetings.sort(key=lambda m: m.get("date", ""), reverse=True)
        if limit is not None:
            meetings = meetings[:limit]
        return meetings

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        path = self.meetings_dir / f"{meeting_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def latest_meeting(self) -> dict[str, Any] | None:
        meetings = self.list_meetings(limit=1)
        return meetings[0] if meetings else None


def today_iso() -> str:
    return date.today().isoformat()

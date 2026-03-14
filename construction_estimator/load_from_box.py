"""
Script to load historical estimator data from Box and build the database.

This script is meant to be run from within a Claude Code session where
the Box MCP connector is available. It uses the Box search and file
content APIs to find and parse all Construction Cost Estimator spreadsheets.

Usage (within Claude Code):
    Tell Claude: "Run load_from_box.py to build the historical database"

    Or programmatically:
        from construction_estimator.load_from_box import build_database
        db = build_database(box_search_fn, box_content_fn)
        db.save("historical_data.json")
"""

from pathlib import Path
from construction_estimator.database import HistoricalDatabase


# Box file IDs for known Construction Cost Estimator files
# Add more file IDs here as you create new estimator spreadsheets
KNOWN_ESTIMATOR_FILES = {
    "1954903405342": "Construction Cost Estimator - 11218 Califa.xlsx",
    "1954910334245": "Copy of LV Construction Cost Estimator - 10953 Whipple.xlsx",
    # Add more projects here as they become available:
    # "FILE_ID": "filename.xlsx",
}

DEFAULT_DB_PATH = Path(__file__).parent / "historical_data.json"


def build_database_from_contents(
    file_contents: dict[str, tuple[str, str]],
) -> HistoricalDatabase:
    """Build database from pre-fetched file contents.

    Args:
        file_contents: Dict of file_id -> (filename, text_content)

    Returns:
        Populated HistoricalDatabase
    """
    db = HistoricalDatabase()

    for file_id, (filename, content) in file_contents.items():
        try:
            project = db.add_project_from_text(
                content=content,
                source_file=filename,
                source_file_id=file_id,
            )
            print(
                f"  Loaded: {project.name} "
                f"({project.gba:,.0f} SF, {project.total_units} units, "
                f"${project.cost_per_sf:,.0f}/SF)"
            )
        except Exception as e:
            print(f"  ERROR loading {filename}: {e}")

    return db


def print_database_summary(db: HistoricalDatabase) -> None:
    """Print a summary of the loaded database."""
    print(f"\n{'=' * 60}")
    print(f"  DATABASE SUMMARY: {db.project_count} projects loaded")
    print(f"{'=' * 60}")

    for p in db.projects:
        print(f"\n  {p.name}")
        print(f"    GBA: {p.gba:,.0f} SF | Units: {p.total_units}")
        print(f"    Type: {p.construction_type} | Floors: {p.num_floors}")
        print(f"    Total: ${p.project_total:,.0f}")
        print(f"    $/SF: ${p.cost_per_sf:,.2f} | $/Unit: ${p.cost_per_unit:,.0f}")
        print(f"    Mix: {p.unit_mix}")
        print(f"    Divisions: {len(p.divisions)}")

    # Cost code coverage
    all_codes = db.get_all_cost_codes()
    print(f"\n  Cost codes tracked: {len(all_codes)}")

    # Overall $/SF range
    totals_per_sf = db.get_project_totals_per_sf()
    if totals_per_sf:
        print(
            f"  $/SF range: ${min(totals_per_sf):,.0f} - "
            f"${max(totals_per_sf):,.0f}"
        )

    print(f"{'=' * 60}\n")

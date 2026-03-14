"""
Build the historical database from all available data sources.

This script is meant to be run from within a Claude Code session where
the Box MCP connector is available.

Usage:
    Tell Claude: "Run build_database.py to build the full historical database"

    The script expects three content variables to be passed in with the
    raw text content from Box:
    - all_projects_content: from Box file 1924340805081
    - ramsgate_content: from Box file 1744642424511
    - francis_content: from Box file 2093828133427
    - califa_content: from Box file 1954903405342
    - whipple_content: from Box file 1954910334245
"""

from pathlib import Path
from construction_estimator.database import HistoricalDatabase
from construction_estimator.multi_parser import (
    parse_all_projects,
    parse_ramsgate_budget,
    parse_francis_budget,
)

DB_PATH = Path(__file__).parent / "construction_estimator" / "historical_data.json"


def build_from_contents(
    all_projects_content: str = "",
    ramsgate_content: str = "",
    francis_content: str = "",
    califa_content: str = "",
    whipple_content: str = "",
) -> HistoricalDatabase:
    """Build the full database from all available content."""
    db = HistoricalDatabase()
    loaded = []

    # 1. All Projects Recent Bids (9 projects)
    if all_projects_content:
        projects = parse_all_projects(all_projects_content)
        for p in projects:
            if p.gba > 0 and p.total_units > 0:
                db.add_project(p)
                loaded.append(
                    f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
                    f"${p.cost_per_sf:,.0f}/SF, ${p.project_total:,.0f}"
                )

    # 2. Ramsgate budget
    if ramsgate_content:
        # Use updated budget (01.10.2025)
        p = parse_ramsgate_budget(ramsgate_content, use_updated=True)
        if p.project_total > 0:
            db.add_project(p)
            loaded.append(
                f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
                f"${p.cost_per_sf:,.0f}/SF, ${p.project_total:,.0f}"
            )

    # 3. Francis budget (standalone, more detailed than All Projects version)
    # Note: Francis also appears in All Projects, but the budget has more detail
    if francis_content:
        p = parse_francis_budget(francis_content)
        if p.project_total > 0:
            # Rename to avoid confusion with All Projects version
            p.name = "Francis (Budget)"
            db.add_project(p)
            loaded.append(
                f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
                f"${p.cost_per_sf:,.0f}/SF, ${p.project_total:,.0f}"
            )

    # 4. Individual estimator files (Califa, Whipple)
    if califa_content:
        p = db.add_project_from_text(
            califa_content,
            source_file="Construction Cost Estimator - 11218 Califa.xlsx",
            source_file_id="1954903405342",
        )
        loaded.append(
            f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
            f"${p.cost_per_sf:,.0f}/SF, ${p.project_total:,.0f}"
        )

    if whipple_content:
        p = db.add_project_from_text(
            whipple_content,
            source_file="Copy of LV Construction Cost Estimator - 10953 Whipple.xlsx",
            source_file_id="1954910334245",
        )
        loaded.append(
            f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
            f"${p.cost_per_sf:,.0f}/SF, ${p.project_total:,.0f}"
        )

    print(f"\n{'=' * 60}")
    print(f"  DATABASE BUILT: {db.project_count} projects loaded")
    print(f"{'=' * 60}")
    for line in loaded:
        print(line)
    print(f"\n  Cost codes tracked: {len(db.get_all_cost_codes())}")
    totals = db.get_project_totals_per_sf()
    if totals:
        print(f"  $/SF range: ${min(totals):,.0f} - ${max(totals):,.0f}")
    print(f"{'=' * 60}\n")

    return db

"""
Full build test - loads all data from Box content files and builds database.

This script reads the content that was already pulled from Box and saved
to the tool-results directory, then parses all projects.
"""

import sys
import json
sys.path.insert(0, r"C:\Users\cma\Dropbox (Personal)\Claude Code")

from construction_estimator.multi_parser import (
    parse_all_projects,
    parse_ramsgate_budget,
    parse_francis_budget,
)
from construction_estimator.database import HistoricalDatabase
from construction_estimator.estimator import EstimatorEngine

# The content was already pulled from Box in this session.
# For the full build, we need to pass content directly.
# This script will be called with content injected.


def build_and_test(
    all_projects_content: str,
    ramsgate_content: str,
    francis_content: str,
):
    """Build database and run a test estimate."""
    db = HistoricalDatabase()

    # 1. Parse All Projects (9 projects)
    print("Parsing All Projects Recent Bids...")
    projects = parse_all_projects(all_projects_content)
    for p in projects:
        if p.gba > 0 and p.total_units > 0:
            db.add_project(p)
            print(
                f"  {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
                f"${p.cost_per_sf:,.0f}/SF, {len(p.divisions)} divs, "
                f"${p.project_total:,.0f}"
            )

    # 2. Parse Ramsgate
    print("\nParsing Ramsgate budget...")
    ramsgate = parse_ramsgate_budget(ramsgate_content, use_updated=True)
    db.add_project(ramsgate)
    print(
        f"  {ramsgate.name}: {ramsgate.gba:,.0f} SF, {ramsgate.total_units} units, "
        f"${ramsgate.cost_per_sf:,.0f}/SF, {len(ramsgate.divisions)} divs, "
        f"${ramsgate.project_total:,.0f}"
    )

    # 3. Parse Francis budget
    print("\nParsing Francis budget...")
    francis = parse_francis_budget(francis_content)
    francis.name = "Francis (Budget)"
    db.add_project(francis)
    print(
        f"  {francis.name}: {francis.gba:,.0f} SF, {francis.total_units} units, "
        f"${francis.cost_per_sf:,.0f}/SF, {len(francis.divisions)} divs, "
        f"${francis.project_total:,.0f}"
    )

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  DATABASE: {db.project_count} projects loaded")
    print(f"  Cost codes: {len(db.get_all_cost_codes())}")
    totals = db.get_project_totals_per_sf()
    if totals:
        print(f"  $/SF range: ${min(totals):,.0f} - ${max(totals):,.0f}")
    print(f"{'=' * 70}")

    # Save database
    db_path = r"C:\Users\cma\Dropbox (Personal)\Claude Code\construction_estimator\historical_data.json"
    db.save(db_path)
    print(f"\nSaved to {db_path}")

    # Run test estimate: 50,000 SF, 85 units (similar to previous test)
    print(f"\n{'=' * 70}")
    print("TEST ESTIMATE: 50,000 SF, 85 units, wood construction")
    print(f"{'=' * 70}")
    engine = EstimatorEngine(db)
    estimate = engine.estimate(
        gba=50000,
        units=85,
        unit_mix={"1BR": 50, "2BR": 35},
        construction_type="wood",
        num_floors=5,
        gc_fee_pct=6.0,
        bonding_pct=1.0,
        admin_pct=2.0,
    )
    print(estimate.summary())

    # Also test Califa-like project (66K SF, 76 units)
    print(f"\n{'=' * 70}")
    print("TEST ESTIMATE: 66,000 SF, 76 units (Califa-like)")
    print(f"{'=' * 70}")
    estimate2 = engine.estimate(
        gba=66000,
        units=76,
        unit_mix={"Studio": 0, "1BR": 46, "2BR": 30},
        construction_type="mixed",
        num_floors=6,
        gc_fee_pct=6.0,
        bonding_pct=1.0,
        admin_pct=2.0,
    )
    print(estimate2.summary())

    return db

"""
CLI entry point for the Construction Cost Estimator.

Usage:
    python -m construction_estimator.main --gba 50000 --units 80 --mix "1BR:50,2BR:30"

Or use interactively:
    python -m construction_estimator.main --interactive
"""

import argparse
import sys
import json
from pathlib import Path

from construction_estimator.database import HistoricalDatabase
from construction_estimator.estimator import EstimatorEngine


DEFAULT_DB_PATH = Path(__file__).parent / "historical_data.json"


def parse_unit_mix(mix_str: str) -> dict[str, int]:
    """Parse unit mix string like '1BR:50,2BR:30' into dict."""
    result = {}
    for part in mix_str.split(","):
        part = part.strip()
        if ":" in part:
            unit_type, count = part.split(":", 1)
            result[unit_type.strip()] = int(count.strip())
    return result


def run_interactive(db: HistoricalDatabase) -> None:
    """Run the estimator interactively."""
    print("\n" + "=" * 60)
    print("  LV CONSTRUCTION COST ESTIMATOR")
    print("=" * 60)
    print(f"\nHistorical database: {db.project_count} projects loaded\n")

    if db.project_count > 0:
        print("Projects in database:")
        for p in db.projects:
            print(
                f"  - {p.name}: {p.gba:,.0f} SF, {p.total_units} units, "
                f"${p.cost_per_sf:,.0f}/SF"
            )
        print()

    # Get project parameters
    gba = float(input("Gross Building Area (SF): ").replace(",", ""))
    units = int(input("Number of units: "))

    mix_str = input(
        "Unit mix (e.g., '1BR:50,2BR:30,Studio:10'): "
    )
    unit_mix = parse_unit_mix(mix_str) if mix_str else {"1BR": units}

    construction_type = (
        input("Construction type (wood/concrete/mixed) [wood]: ").strip()
        or "wood"
    )
    num_floors = int(input("Number of floors [5]: ").strip() or "5")

    gc_fee = float(input("GC fee % [6]: ").strip() or "6")
    bonding = float(input("Bonding % [1]: ").strip() or "1")
    admin = float(input("Admin % [2]: ").strip() or "2")

    # Generate estimate
    engine = EstimatorEngine(db)
    estimate = engine.estimate(
        gba=gba,
        units=units,
        unit_mix=unit_mix,
        construction_type=construction_type,
        num_floors=num_floors,
        gc_fee_pct=gc_fee,
        bonding_pct=bonding,
        admin_pct=admin,
    )

    print("\n" + estimate.summary())

    # Option to see line item detail
    detail = input("\nShow line item detail? (y/n) [n]: ").strip().lower()
    if detail == "y":
        print_line_item_detail(estimate)

    # Option to export
    export = input("\nExport to JSON? (y/n) [n]: ").strip().lower()
    if export == "y":
        export_path = input("Export path [estimate.json]: ").strip() or "estimate.json"
        export_estimate(estimate, export_path)
        print(f"Exported to {export_path}")


def print_line_item_detail(estimate):
    """Print detailed line items for each division."""
    for div in estimate.divisions:
        print(f"\n{'=' * 80}")
        print(
            f"Div. {div.number} - {div.name}  "
            f"(${div.estimated_total:,.0f})"
        )
        print(f"{'=' * 80}")
        print(
            f"  {'Code':<18} {'Description':<30} "
            f"{'Total':>12} {'$/SF':>8} {'$/Unit':>8} "
            f"{'Conf':>5} {'Pts':>3}"
        )
        print(f"  {'-' * 95}")
        for item in div.line_items:
            print(
                f"  {item.cost_code:<18} "
                f"{item.description[:30]:<30} "
                f"${item.estimated_total:>10,.0f} "
                f"${item.estimated_per_sf:>6,.2f} "
                f"${item.estimated_per_unit:>6,.0f} "
                f"{item.confidence:>4.0%} "
                f"{item.data_points:>3d}"
            )


def export_estimate(estimate, path: str) -> None:
    """Export estimate to JSON."""
    data = {
        "target": {
            "gba": estimate.target_gba,
            "units": estimate.target_units,
            "unit_mix": estimate.target_unit_mix,
            "construction_type": estimate.target_construction_type,
        },
        "totals": {
            "project_total": estimate.project_total,
            "project_subtotal": estimate.project_subtotal,
            "admin_total": estimate.admin_total,
            "cost_per_sf": estimate.cost_per_sf,
            "cost_per_unit": estimate.cost_per_unit,
            "low_total": estimate.low_total,
            "high_total": estimate.high_total,
        },
        "divisions": [
            {
                "number": d.number,
                "name": d.name,
                "estimated_total": d.estimated_total,
                "estimated_per_sf": d.estimated_per_sf,
                "estimated_per_unit": d.estimated_per_unit,
                "low_total": d.low_total,
                "high_total": d.high_total,
                "line_items": [
                    {
                        "cost_code": li.cost_code,
                        "description": li.description,
                        "estimated_total": li.estimated_total,
                        "estimated_per_sf": li.estimated_per_sf,
                        "estimated_per_unit": li.estimated_per_unit,
                        "low_total": li.low_total,
                        "high_total": li.high_total,
                        "confidence": li.confidence,
                        "data_points": li.data_points,
                        "method": li.method,
                    }
                    for li in d.line_items
                ],
            }
            for d in estimate.divisions
        ],
        "similar_projects": [
            {"name": name, "score": score}
            for name, score in zip(
                estimate.similar_projects, estimate.match_scores
            )
        ],
    }
    Path(path).write_text(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="LV Construction Cost Estimator"
    )
    parser.add_argument(
        "--db", type=str, default=str(DEFAULT_DB_PATH),
        help="Path to historical database JSON file",
    )
    parser.add_argument("--interactive", "-i", action="store_true")
    parser.add_argument("--gba", type=float, help="Gross Building Area (SF)")
    parser.add_argument("--units", type=int, help="Number of units")
    parser.add_argument(
        "--mix", type=str, help="Unit mix (e.g., '1BR:50,2BR:30')"
    )
    parser.add_argument(
        "--type", type=str, default="wood",
        choices=["wood", "concrete", "mixed"],
    )
    parser.add_argument("--floors", type=int, default=5)
    parser.add_argument("--gc-fee", type=float, default=6.0)
    parser.add_argument("--bonding", type=float, default=1.0)
    parser.add_argument("--admin", type=float, default=2.0)
    parser.add_argument("--detail", action="store_true", help="Show line items")
    parser.add_argument("--export", type=str, help="Export to JSON file")

    args = parser.parse_args()

    # Load database
    db = HistoricalDatabase()
    db_path = Path(args.db)
    if db_path.exists():
        db.load(str(db_path))
        print(f"Loaded {db.project_count} historical projects from {db_path}")
    else:
        print(f"No database found at {db_path}")
        print("Use the load_from_box.py script to build the database first.")
        if not args.interactive:
            sys.exit(1)

    if args.interactive:
        run_interactive(db)
        return

    if not args.gba or not args.units:
        parser.error("--gba and --units are required (or use --interactive)")

    unit_mix = parse_unit_mix(args.mix) if args.mix else {"1BR": args.units}

    engine = EstimatorEngine(db)
    estimate = engine.estimate(
        gba=args.gba,
        units=args.units,
        unit_mix=unit_mix,
        construction_type=args.type,
        num_floors=args.floors,
        gc_fee_pct=args.gc_fee,
        bonding_pct=args.bonding,
        admin_pct=args.admin,
    )

    print(estimate.summary())

    if args.detail:
        print_line_item_detail(estimate)

    if args.export:
        export_estimate(estimate, args.export)
        print(f"\nExported to {args.export}")


if __name__ == "__main__":
    main()

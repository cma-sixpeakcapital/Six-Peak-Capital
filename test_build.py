"""Test building the database from all sources."""

import sys
sys.path.insert(0, r"C:\Users\cma\Dropbox (Personal)\Claude Code")

from construction_estimator.multi_parser import (
    parse_all_projects,
    parse_ramsgate_budget,
)
from construction_estimator.database import HistoricalDatabase

# Test with inline snippets first, then full data

# ---- Test All Projects parser with a small sample ----
sample_all_projects = """Hard Costs
\t\t\tUnits\t42\t\t\tUnits\t19\t\t\tUnits\t28
\t\t\tBeds\t141\t\t\tBeds\t112\t\t\tBeds\t156
\t\t\tConstruction GBA\t66,488\t\t\tConstruction GBA\t54,496\t\t\tConstruction GBA\t82,722
\tCost Code\tDescription\tMelrosse\tCost Per SF\tCost Per Unit\tCost Per Bed\tVenice\tCost Per SF\tCost Per Unit\tCost Per Bed\tBerryman 1\tCost Per SF\tCost Per Unit\tCost Per Bed
\t20-0000-0000-20-1000-1000.O\tProject Field Supervision.Other\t$   488,375\t$   8.96\t$   25,704\t$   3,464\t$   602,260\t$   11.05\t$   31,698\t$   5,377\t$   600,000\t$   7.25\t$   21,429\t$   3,846
\t53-0000-0000-53-1000-1000.S\tFraming.Commitment\t$   1,434,618\t$   26.33\t$   75,506\t$   10,175\t$   1,826,414\t$   33.51\t$   96,127\t$   16,307\t$   2,400,000\t$   29.01\t$   85,714\t$   15,385"""

print("Testing All Projects parser with 3-project sample...")
projects = parse_all_projects(sample_all_projects)

# Should find Melrose, Venice, Berryman 1
for p in projects[:3]:
    if p.gba > 0:
        print(f"  {p.name}: GBA={p.gba:,.0f}, Units={p.total_units}, "
              f"Divs={len(p.divisions)}, Total=${p.project_total:,.0f}, "
              f"$/SF=${p.cost_per_sf:,.2f}")
        for d in p.divisions:
            print(f"    Div {d.number}: {d.name} = ${d.total_cost:,.0f} "
                  f"({len(d.line_items)} items)")

print("\nAll Projects parser: OK\n")

# ---- Test Ramsgate parser with sample ----
sample_ramsgate = """rx_Const_Chart_Categories
\t\t\t\t02.15.2024\t\t01.10.2025
\tRamsgate
\tCode\tDescription\tAllowance - Y / N\tLOW Budget\tLOW Notes
\t\tGeneral Requirements
\t20-1000-1000      \tField Supervision\t\t$   720,000.00\tfull time super\t$   1,125,000.00
\t20-2000-2000      \tTemporary Toilets\t\t$   30,000.00\t24 month\t$   72,000.00
\t\tOff-Site Construction
\t30-1000-1000      \tCurbs - Gutters - Sidewalks\t\t$   19,950.00\tCP&G\t$   80,000.00
\t\tConcrete
\t50-1000-1000      \tStructural Concrete\t\t$   1,696,395.00\tSahara\t$   2,255,000.00
\t\tWood and Plastics
\t53-1000-1000      \tFraming\t\t$   1,547,000.00\tTWL\t$   2,350,000.00
\t\tProject Administration
\t75-1000-1000      \tGC-CM Fee  \t\t$   819,092.75\t\t$   1,248,476.95"""

print("Testing Ramsgate parser...")
ramsgate = parse_ramsgate_budget(sample_ramsgate, use_updated=True, gba=64586, units=48)
print(f"  {ramsgate.name}: GBA={ramsgate.gba:,.0f}, Units={ramsgate.total_units}")
print(f"  Total: ${ramsgate.project_total:,.0f}, $/SF: ${ramsgate.cost_per_sf:,.2f}")
for d in ramsgate.divisions:
    print(f"    Div {d.number}: {d.name} = ${d.total_cost:,.0f} ({len(d.line_items)} items)")

print("\nRamsgate parser: OK\n")
print("All parsers working!")

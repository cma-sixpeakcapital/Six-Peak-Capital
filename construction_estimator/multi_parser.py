"""
Parsers for additional data formats beyond the standard LV estimator.

Handles:
1. "All Projects Recent Bids" multi-project columnar format
2. Ramsgate-style budget format (standard cost codes, LOW + updated columns)
3. Francis-style budget format (division-based, no standard cost codes)
"""

import re
from construction_estimator.models import Project, Division, CostLineItem
from construction_estimator.parser import COST_CODE_TO_DIV, DIVISION_MAP, _parse_currency


def _parse_number(value: str) -> float:
    """Parse a number string like '2,110,113' or '- 0' to float."""
    if not value:
        return 0.0
    cleaned = value.replace(",", "").replace("$", "").replace("-", "").strip()
    if not cleaned or cleaned == "0":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalize_cost_code(long_code: str) -> str:
    """Convert long cost code to standard format.

    '20-0000-0000-20-1000-1000.O' -> '20-1000-1000'
    '75-0000-0000-75-1000-3000.O' -> '75-1000-3000'
    """
    # Extract the meaningful part: XX-YYYY-ZZZZ from XX-0000-0000-XX-YYYY-ZZZZ.suffix
    match = re.search(r"(\d{2})-\d{4}-\d{4}-(\d{2}-\d{4}-\d{4})", long_code)
    if match:
        return match.group(2)
    # Fallback: try standard format
    match = re.search(r"(\d{2}-\d{4}-\d{4})", long_code)
    if match:
        return match.group(1)
    return long_code


def _cost_code_to_division(cost_code: str) -> tuple[int, str]:
    """Map a cost code prefix to division number and name."""
    prefix = cost_code[:2]
    div_num = COST_CODE_TO_DIV.get(prefix, 0)
    div_name = DIVISION_MAP.get(div_num, "UNKNOWN")
    if prefix == "75":
        div_name = "PROJECT ADMINISTRATION"
    return div_num, div_name


# ---------------------------------------------------------------------------
# All Projects Recent Bids parser
# ---------------------------------------------------------------------------

# Project name order in the All Projects file columns
ALL_PROJECTS_NAMES = [
    "Melrose", "Venice", "Berryman 1", "Berryman 2",
    "Reading", "Wilton", "Francis", "Crenshaw", "Nelrose",
]


def parse_all_projects(content: str) -> list[Project]:
    """Parse the 'All Projects Recent Bids' multi-project columnar format.

    Returns a list of Project objects, one per project column.
    """
    lines = content.split("\n")

    # Parse header to get project characteristics
    project_data = {name: {} for name in ALL_PROJECTS_NAMES}

    # Parse header rows (Units, Beds, Construction Garage, Above Grade, GBA, GMP)
    for line in lines[:20]:
        parts = [p.strip() for p in line.split("\t")]
        if not parts:
            continue
        joined = "\t".join(parts)

        for key in ["Units", "Beds", "Construction Garage", "Above Grade",
                     "Construction GBA", "GMP Date", "Completed"]:
            if key in joined:
                _parse_header_row(parts, key, project_data)
                break

    # Build project objects with characteristics
    projects = []
    for name in ALL_PROJECTS_NAMES:
        pd = project_data[name]
        gba = pd.get("Construction GBA", 0.0)
        units = int(pd.get("Units", 0))
        garage = pd.get("Construction Garage", 0.0)
        above_grade = pd.get("Above Grade", 0.0)

        project = Project(
            name=name,
            address="",
            lot_size=0.0,
            gba=gba,
            gba_concrete=garage,  # garage is concrete
            gba_wood=above_grade,  # above grade is wood-frame
            total_units=units,
            unit_mix={},
            floor_areas={},
            num_floors=0,
            source_file="All Projects Recent Bids",
            source_file_id="1924340805081",
        )
        projects.append(project)

    # Parse cost data rows
    divisions_by_project = {name: {} for name in ALL_PROJECTS_NAMES}

    for line in lines:
        parts = [p.strip() for p in line.split("\t")]
        if not parts:
            continue
        joined = " ".join(parts)

        # Skip header/summary rows
        if "Total Hard Costs" in joined or "Cost Code" in joined:
            continue
        if "Contingency" in joined and "20-9000-1000" not in joined:
            continue

        # Look for cost code in the line
        code_match = re.search(
            r"(\d{2}-\d{4}-\d{4}-\d{2}-\d{4}-\d{4}\.\w+)", joined
        )
        if not code_match:
            continue

        long_code = code_match.group(1)
        cost_code = _normalize_cost_code(long_code)
        div_num, div_name = _cost_code_to_division(cost_code)

        # Find description (next non-empty part after cost code)
        description = _extract_description_from_parts(parts, long_code)

        # Extract dollar amounts for each project
        # Format: cost_code, description, then for each project:
        #   $total, $per_sf, $per_unit, $per_bed (4 values per project)
        dollar_values = []
        for p in parts:
            if "$" in p:
                dollar_values.append(_parse_currency(p))

        # Each project gets 4 dollar values: total, per_sf, per_unit, per_bed
        for i, name in enumerate(ALL_PROJECTS_NAMES):
            base = i * 4
            if base + 2 < len(dollar_values):
                total = dollar_values[base]
                per_sf = dollar_values[base + 1]
                per_unit = dollar_values[base + 2]

                if div_num not in divisions_by_project[name]:
                    divisions_by_project[name][div_num] = Division(
                        number=div_num,
                        name=div_name,
                        total_cost=0.0,
                        cost_per_sf=0.0,
                        cost_per_unit=0.0,
                    )

                div = divisions_by_project[name][div_num]
                item = CostLineItem(
                    cost_code=cost_code,
                    description=description,
                    division_number=div_num,
                    division_name=div_name,
                    total_cost=total,
                    cost_per_sf=per_sf,
                    cost_per_unit=per_unit,
                )
                div.line_items.append(item)
                div.total_cost += total

    # Assemble divisions into projects and calculate totals
    for i, name in enumerate(ALL_PROJECTS_NAMES):
        project = projects[i]
        divs = divisions_by_project[name]

        for div_num in sorted(divs.keys()):
            div = divs[div_num]
            if project.gba > 0:
                div.cost_per_sf = div.total_cost / project.gba
            if project.total_units > 0:
                div.cost_per_unit = div.total_cost / project.total_units
            project.divisions.append(div)

        # Calculate totals
        subtotal = sum(
            d.total_cost for d in project.divisions if d.number != 99
        )
        admin = sum(
            d.total_cost for d in project.divisions if d.number == 99
        )
        project.project_subtotal = subtotal
        project.admin_total = admin
        project.project_total = subtotal + admin
        if project.gba > 0:
            project.cost_per_sf = project.project_total / project.gba
        if project.total_units > 0:
            project.cost_per_unit = project.project_total / project.total_units

    return projects


def _parse_header_row(
    parts: list[str], key: str, project_data: dict
) -> None:
    """Parse a header row and extract values for each project."""
    # Find all occurrences of the key and the value that follows
    key_indices = [i for i, p in enumerate(parts) if p == key]
    for idx, ki in enumerate(key_indices):
        if ki + 1 < len(parts) and idx < len(ALL_PROJECTS_NAMES):
            val = parts[ki + 1].replace(",", "").strip()
            try:
                project_data[ALL_PROJECTS_NAMES[idx]][key] = float(val)
            except (ValueError, IndexError):
                project_data[ALL_PROJECTS_NAMES[idx]][key] = val


def _extract_description_from_parts(
    parts: list[str], cost_code: str
) -> str:
    """Extract description text from parts after the cost code."""
    found = False
    for p in parts:
        if cost_code in p:
            # Description might be in the same field after the code
            after = p.replace(cost_code, "").strip()
            if after:
                return after
            found = True
            continue
        if found and p and not p.startswith("$"):
            return p
    return ""


# ---------------------------------------------------------------------------
# Ramsgate budget parser
# ---------------------------------------------------------------------------

# Division section headers in the Ramsgate format
RAMSGATE_DIVISIONS = {
    "General Requirements": (1, "GENERAL REQUIREMENTS"),
    "Off-Site Construction": (2, "OFF-SITE CONSTRUCTION"),
    "On-Site Construction": (2, "ON-SITE CONSTRUCTION"),
    "Concrete": (3, "CONCRETE"),
    "Masonry": (4, "MASONRY"),
    "Metals": (5, "METALS"),
    "Wood and Plastics": (6, "WOOD AND PLASTICS"),
    "Protection": (7, "THERMAL & MOISTURE PROTECTION"),
    "Doors and Windows": (8, "DOORS, WINDOWS & GLAZING"),
    "Finishes": (9, "FINISHES"),
    "Specialties": (10, "SPECIALTIES"),
    "Equipment": (11, "EQUIPMENT"),
    "Furnishings": (12, "FURNISHINGS"),
    "Special Construction": (13, "SPECIAL CONSTRUCTION"),
    "Conveying Systems": (14, "CONVEYING SYSTEMS"),
    "Mechanical": (15, "MECHANICAL"),
    "Electrical": (16, "ELECTRICAL"),
    "Project Administration": (99, "PROJECT ADMINISTRATION"),
}


def parse_ramsgate_budget(
    content: str,
    use_updated: bool = True,
    gba: float = 64_586.0,
    units: int = 48,
) -> Project:
    """Parse the Ramsgate budget format.

    Args:
        content: Raw text from Box
        use_updated: If True, use the 01.10.2025 updated budget column;
                     if False, use the LOW Budget column
        gba: Known GBA for Ramsgate (from Crenshaw data or provided)
        units: Known unit count
    """
    lines = content.split("\n")
    current_div_num = 0
    current_div_name = ""
    divisions: dict[int, Division] = {}

    for line in lines:
        parts = [p.strip() for p in line.split("\t")]
        if not parts:
            continue

        joined = " ".join(p for p in parts if p)

        # Check for division section headers
        for section_name, (div_num, div_name) in RAMSGATE_DIVISIONS.items():
            if section_name in joined and "Total" not in joined:
                # Simple heuristic: section header is short with the name
                stripped_parts = [p for p in parts if p]
                if len(stripped_parts) <= 3:
                    current_div_num = div_num
                    current_div_name = div_name
                    if div_num not in divisions:
                        divisions[div_num] = Division(
                            number=div_num,
                            name=div_name,
                            total_cost=0.0,
                            cost_per_sf=0.0,
                            cost_per_unit=0.0,
                        )
                    break

        # Look for cost code lines: "20-1000-1000" format
        code_match = re.search(r"(\d{2}-\d{4}-\d{4})", joined)
        if not code_match or current_div_num == 0:
            continue

        cost_code = code_match.group(1)

        # Find description
        code_idx = None
        for i, p in enumerate(parts):
            if cost_code in p:
                code_idx = i
                break

        description = ""
        if code_idx is not None and code_idx + 1 < len(parts):
            description = parts[code_idx + 1].strip()

        # Extract dollar amounts
        dollar_values = []
        for p in parts:
            if "$" in p:
                dollar_values.append(_parse_currency(p))

        if not dollar_values:
            continue

        # In Ramsgate format:
        # LOW Budget is typically the first dollar value
        # Updated budget is typically the second (if use_updated)
        if use_updated and len(dollar_values) >= 2:
            total = dollar_values[1]
        else:
            total = dollar_values[0]

        if total <= 0:
            # Fall back to LOW if updated is zero
            total = dollar_values[0] if dollar_values[0] > 0 else 0.0

        per_sf = total / gba if gba > 0 else 0.0
        per_unit = total / units if units > 0 else 0.0

        if current_div_num not in divisions:
            divisions[current_div_num] = Division(
                number=current_div_num,
                name=current_div_name,
                total_cost=0.0,
                cost_per_sf=0.0,
                cost_per_unit=0.0,
            )

        div = divisions[current_div_num]
        item = CostLineItem(
            cost_code=cost_code,
            description=description,
            division_number=current_div_num,
            division_name=current_div_name,
            total_cost=total,
            cost_per_sf=per_sf,
            cost_per_unit=per_unit,
        )
        div.line_items.append(item)
        div.total_cost += total

    # Build project
    sorted_divs = []
    for div_num in sorted(divisions.keys()):
        div = divisions[div_num]
        if gba > 0:
            div.cost_per_sf = div.total_cost / gba
        if units > 0:
            div.cost_per_unit = div.total_cost / units
        sorted_divs.append(div)

    subtotal = sum(d.total_cost for d in sorted_divs if d.number != 99)
    admin = sum(d.total_cost for d in sorted_divs if d.number == 99)

    project = Project(
        name="Ramsgate",
        address="9033 Ramsgate",
        lot_size=0.0,
        gba=gba,
        gba_concrete=0.0,
        gba_wood=gba,  # wood frame
        total_units=units,
        unit_mix={},
        floor_areas={},
        num_floors=5,
        divisions=sorted_divs,
        project_subtotal=subtotal,
        admin_total=admin,
        project_total=subtotal + admin,
        source_file="1.10.25 Ramsgate Budget.xlsx",
        source_file_id="1744642424511",
    )
    if gba > 0:
        project.cost_per_sf = project.project_total / gba
    if units > 0:
        project.cost_per_unit = project.project_total / units

    return project


# ---------------------------------------------------------------------------
# Francis budget parser
# ---------------------------------------------------------------------------

# Map Francis division numbers to our standard division numbers
FRANCIS_DIV_MAP = {
    1: (1, "GENERAL REQUIREMENTS"),
    2: (2, "OFF-SITE CONSTRUCTION"),
    3: (3, "CONCRETE"),
    4: (4, "MASONRY"),
    5: (5, "METALS"),
    6: (6, "WOOD AND PLASTICS"),
    7: (7, "THERMAL & MOISTURE PROTECTION"),
    8: (8, "DOORS, WINDOWS & GLAZING"),
    9: (9, "FINISHES"),
    10: (10, "SPECIALTIES"),
    11: (11, "EQUIPMENT"),
    12: (12, "FURNISHINGS"),
    13: (13, "SPECIAL CONSTRUCTION"),
    14: (14, "CONVEYING SYSTEMS"),
    15: (15, "MECHANICAL"),
    16: (16, "ELECTRICAL"),
    # Francis uses 2020 CSI MasterFormat divisions - map to standard
    21: (15, "MECHANICAL"),      # Fire Suppression -> Mechanical
    22: (15, "MECHANICAL"),      # Plumbing -> Mechanical
    23: (15, "MECHANICAL"),      # HVAC -> Mechanical
    26: (16, "ELECTRICAL"),      # Electrical -> Electrical
    27: (16, "ELECTRICAL"),      # Communications -> Electrical
    28: (16, "ELECTRICAL"),      # Safety & Security -> Electrical
    31: (2, "ON-SITE CONSTRUCTION"),   # Shoring & Earthwork -> On-Site
    32: (2, "ON-SITE CONSTRUCTION"),   # Exterior Improvements -> On-Site
    33: (15, "MECHANICAL"),      # Utilities -> Mechanical
}


def parse_francis_budget(content: str) -> Project:
    """Parse the Francis budget format.

    Francis uses division numbers instead of standard cost codes.
    Tab-delimited columns (0-indexed):
      0: (empty)
      1: DIVISION number
      2: COST CODE (often empty)
      3: TRADE DESCRIPTION
      4: QUANTITY
      5: UNIT
      6: COST / UNIT
      7: UNIT (repeat)
      8: BUDGET
      9: PER SF
      10: PER UNIT
      11: NOTES
      12+: tracking columns
    """
    lines = content.split("\n")
    gba = 137_870.0  # GSF from header
    units = 232  # Total units from header

    # Try to extract GBA and units from header
    for line in lines[:15]:
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        joined = " ".join(parts)
        if "Total" in joined and "UNITS" in joined:
            for i, p in enumerate(parts):
                if p == "Total" and i + 1 < len(parts):
                    try:
                        units = int(parts[i + 1].replace(",", ""))
                    except ValueError:
                        pass
        if "GSF" in joined:
            for i, p in enumerate(parts):
                if p == "GSF" and i + 1 < len(parts):
                    try:
                        gba = float(parts[i + 1].replace(",", ""))
                    except ValueError:
                        pass

    divisions: dict[int, Division] = {}
    current_div_num = 0
    current_div_name = ""
    line_item_counter: dict[int, int] = {}

    for line in lines:
        parts = line.split("\t")
        # Use raw tab positions (not stripped) to preserve column indices
        stripped_parts = [p.strip() for p in parts]

        # Get division number from column 1
        div_col = stripped_parts[1] if len(stripped_parts) > 1 else ""
        desc_col = stripped_parts[3] if len(stripped_parts) > 3 else ""
        budget_col = stripped_parts[8] if len(stripped_parts) > 8 else ""
        per_sf_col = stripped_parts[9] if len(stripped_parts) > 9 else ""
        per_unit_col = stripped_parts[10] if len(stripped_parts) > 10 else ""

        if not div_col:
            continue

        # Try to parse division number
        try:
            line_div = int(div_col)
        except ValueError:
            continue

        # Detect division header rows (all caps description, with budget total)
        if desc_col and desc_col == desc_col.upper() and len(desc_col) > 3:
            if line_div in FRANCIS_DIV_MAP:
                current_div_num, current_div_name = FRANCIS_DIV_MAP[line_div]
            else:
                current_div_num = line_div
                current_div_name = desc_col
            if current_div_num not in divisions:
                divisions[current_div_num] = Division(
                    number=current_div_num,
                    name=current_div_name,
                    total_cost=0.0,
                    cost_per_sf=0.0,
                    cost_per_unit=0.0,
                )
            continue

        if current_div_num == 0 or not desc_col:
            continue

        # If we see a new division number, switch
        if line_div in FRANCIS_DIV_MAP and line_div != current_div_num:
            current_div_num, current_div_name = FRANCIS_DIV_MAP[line_div]
            if current_div_num not in divisions:
                divisions[current_div_num] = Division(
                    number=current_div_num,
                    name=current_div_name,
                    total_cost=0.0,
                    cost_per_sf=0.0,
                    cost_per_unit=0.0,
                )

        # Parse budget from column 8
        budget = _parse_number(budget_col)
        if budget <= 0:
            continue

        per_sf = _parse_number(per_sf_col)
        per_unit_val = _parse_number(per_unit_col)

        # Generate synthetic cost code
        if current_div_num not in line_item_counter:
            line_item_counter[current_div_num] = 0
        line_item_counter[current_div_num] += 1
        seq = line_item_counter[current_div_num]

        prefix_map = {v: k for k, v in COST_CODE_TO_DIV.items()}
        prefix = prefix_map.get(current_div_num, str(current_div_num).zfill(2))
        cost_code = f"{prefix}-{seq:04d}-1000"

        if per_sf == 0 and gba > 0:
            per_sf = budget / gba
        if per_unit_val == 0 and units > 0:
            per_unit_val = budget / units

        div = divisions[current_div_num]
        item = CostLineItem(
            cost_code=cost_code,
            description=desc_col,
            division_number=current_div_num,
            division_name=current_div_name,
            total_cost=budget,
            cost_per_sf=per_sf,
            cost_per_unit=per_unit_val,
        )
        div.line_items.append(item)
        div.total_cost += budget

    # Build project
    sorted_divs = []
    for div_num in sorted(divisions.keys()):
        div = divisions[div_num]
        if gba > 0:
            div.cost_per_sf = div.total_cost / gba
        if units > 0:
            div.cost_per_unit = div.total_cost / units
        sorted_divs.append(div)

    subtotal = sum(d.total_cost for d in sorted_divs if d.number != 99)
    admin = sum(d.total_cost for d in sorted_divs if d.number == 99)

    project = Project(
        name="Francis",
        address="2859 Francis Avenue",
        lot_size=0.0,
        gba=gba,
        gba_concrete=0.0,  # Type I portion
        gba_wood=0.0,  # Type III portion
        total_units=units,
        unit_mix={},
        floor_areas={},
        num_floors=0,
        divisions=sorted_divs,
        project_subtotal=subtotal,
        admin_total=admin,
        project_total=subtotal + admin,
        source_file="FRANCIS BUDGET.011626.xlsx",
        source_file_id="2093828133427",
    )
    if gba > 0:
        project.cost_per_sf = project.project_total / gba
    if units > 0:
        project.cost_per_unit = project.project_total / units

    return project

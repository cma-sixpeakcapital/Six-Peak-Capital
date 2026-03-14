"""
Parser for LV Construction Cost Estimator spreadsheets.

Handles the standard CSI division-based format used in files like:
- "Construction Cost Estimator - 11218 Califa.xlsx"
- "Copy of LV Construction Cost Estimator - 10953 Whipple.xlsx"

The spreadsheets have three key sheets:
1. SUMMARY - Division-level totals
2. Hard Cost Estimate - Detailed line items with cost codes
3. Target Property - Project characteristics (GBA, units, etc.)
"""

import re
from construction_estimator.models import Project, Division, CostLineItem


# Standard division mapping from the LV estimator format
DIVISION_MAP = {
    1: "GENERAL REQUIREMENTS",
    2: "OFF-SITE CONSTRUCTION",  # Note: Div 2 appears twice (off-site and on-site)
    3: "CONCRETE",
    4: "MASONRY",
    5: "METALS",
    6: "WOOD AND PLASTICS",
    7: "THERMAL & MOISTURE PROTECTION",
    8: "DOORS, WINDOWS & GLAZING",
    9: "FINISHES",
    10: "SPECIALTIES",
    11: "EQUIPMENT",
    12: "FURNISHINGS",
    13: "SPECIAL CONSTRUCTION",
    14: "CONVEYING SYSTEMS",
    15: "MECHANICAL",
    16: "ELECTRICAL",
}

# Cost code prefix to division number mapping
COST_CODE_TO_DIV = {
    "20": 1,   # General Requirements
    "30": 2,   # Off-Site Construction
    "40": 2,   # On-Site Construction (also Div 2)
    "50": 3,   # Concrete
    "51": 4,   # Masonry
    "52": 5,   # Metals
    "53": 6,   # Wood and Plastics
    "54": 7,   # Thermal & Moisture Protection
    "55": 8,   # Doors, Windows & Glazing
    "56": 9,   # Finishes
    "57": 10,  # Specialties
    "58": 11,  # Equipment
    "59": 12,  # Furnishings
    "60": 13,  # Special Construction
    "61": 14,  # Conveying Systems
    "62": 15,  # Mechanical
    "63": 16,  # Electrical
    "75": 99,  # Project Administration
}


def _parse_currency(value: str) -> float:
    """Parse a currency string like '$   1,280,698' or '$   - 0' to float."""
    if not value:
        return 0.0
    cleaned = value.replace("$", "").replace(",", "").replace("-", "").strip()
    if not cleaned or cleaned == "0":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_percentage(value: str) -> float | None:
    """Parse a percentage string like '6%' to float."""
    if not value:
        return None
    match = re.search(r"([\d.]+)\s*%", str(value))
    if match:
        return float(match.group(1))
    return None


class EstimatorParser:
    """Parses LV Construction Cost Estimator text content into Project objects.

    Works with the text content extracted from Box via get_file_content,
    which returns the spreadsheet as tab-separated text.
    """

    def parse_text_content(
        self, content: str, source_file: str = "", source_file_id: str = ""
    ) -> Project:
        """Parse the text content from a Box file extraction.

        Args:
            content: Raw text content from Box get_file_content
            source_file: Original filename
            source_file_id: Box file ID

        Returns:
            Populated Project object
        """
        sections = self._split_sections(content)

        # Parse Target Property first to get project characteristics
        project = self._parse_target_property(
            sections.get("Target Property", "")
        )
        project.source_file = source_file
        project.source_file_id = source_file_id

        # Parse Hard Cost Estimate for detailed line items
        hard_cost_text = sections.get("Hard Cost Estimate", "")
        if hard_cost_text:
            project.divisions = self._parse_hard_cost_estimate(hard_cost_text)

        # Calculate totals from divisions
        self._calculate_totals(project)

        return project

    def _split_sections(self, content: str) -> dict[str, str]:
        """Split the content into named sections."""
        sections = {}
        current_section = None
        current_lines = []

        for line in content.split("\n"):
            stripped = line.strip()
            # Section headers appear as standalone words
            if stripped in (
                "SUMMARY",
                "Hard Cost Estimate",
                "Target Property",
            ):
                if current_section:
                    sections[current_section] = "\n".join(current_lines)
                current_section = stripped
                current_lines = []
            else:
                current_lines.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_lines)

        return sections

    def _parse_target_property(self, text: str) -> Project:
        """Parse the Target Property section."""
        address = ""
        lot_size = 0.0
        floor_areas = {}
        total_gba = 0.0
        gba_concrete = 0.0
        gba_wood = 0.0
        total_units = 0
        unit_mix = {"Studio": 0, "1BR": 0, "2BR": 0}

        for line in text.split("\n"):
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if not parts:
                continue

            # Match key fields
            line_text = "\t".join(parts).lower()

            if "address" in line_text:
                address = parts[-1] if len(parts) > 1 else ""
            elif "lot size" in line_text:
                lot_size = self._extract_number(parts)
            elif "total pro-forma gba" in line_text and "concrete" not in line_text and "wood" not in line_text:
                total_gba = self._extract_number(parts)
            elif "gba concrete" in line_text:
                gba_concrete = self._extract_number(parts)
            elif "gba wood" in line_text:
                gba_wood = self._extract_number(parts)
            elif "total units" in line_text:
                total_units = int(self._extract_number(parts))
            elif "studio" in line_text:
                unit_mix["Studio"] = int(self._extract_number(parts))
            elif "1br" in line_text:
                unit_mix["1BR"] = int(self._extract_number(parts))
            elif "2br" in line_text:
                unit_mix["2BR"] = int(self._extract_number(parts))
            elif re.search(r"\d+(st|nd|rd|th)\s+floor", line_text):
                floor_name = parts[0]
                area = self._extract_number(parts)
                if area > 0:
                    floor_areas[floor_name] = area
            elif "ground floor" in line_text:
                area = self._extract_number(parts)
                if area > 0:
                    floor_areas["Ground Floor Parking"] = area

        num_floors = len([a for a in floor_areas.values() if a > 0])

        # Derive name from address
        name = address if address else ""

        return Project(
            name=name,
            address=address,
            lot_size=lot_size,
            gba=total_gba,
            gba_concrete=gba_concrete,
            gba_wood=gba_wood,
            total_units=total_units,
            unit_mix=unit_mix,
            floor_areas=floor_areas,
            num_floors=num_floors,
        )

    def _parse_hard_cost_estimate(self, text: str) -> list[Division]:
        """Parse the Hard Cost Estimate section into divisions."""
        divisions = []
        current_div = None
        gba = 0.0
        total_units = 0

        for line in text.split("\n"):
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if not parts:
                continue

            joined = " ".join(parts)

            # Extract GBA and units from header
            if "Construction GBA" in joined:
                for i, p in enumerate(parts):
                    if p == "Construction GBA" and i + 1 < len(parts):
                        try:
                            gba = float(parts[i + 1].replace(",", ""))
                        except ValueError:
                            pass
                    if p == "Total Units" and i + 1 < len(parts):
                        try:
                            total_units = int(parts[i + 1].replace(",", ""))
                        except ValueError:
                            pass
                continue

            # Check for division header line: "Div. X - NAME"
            div_match = re.search(
                r"Div\.\s*(\d+)\s*-\s*([A-Z][A-Z &,/\-]+)", joined
            )
            if div_match:
                # Parse division totals from this line
                div_num = int(div_match.group(1))
                div_name = div_match.group(2).strip()

                # Extract costs - look for dollar amounts
                costs = self._extract_costs_from_parts(parts)

                current_div = Division(
                    number=div_num,
                    name=div_name,
                    cost_per_unit=costs.get("per_unit", 0.0),
                    cost_per_sf=costs.get("per_sf", 0.0),
                    total_cost=costs.get("total", 0.0),
                )
                divisions.append(current_div)
                continue

            # Check for PROJECT ADMINISTRATION
            if "PROJECT ADMINISTRATION" in joined:
                costs = self._extract_costs_from_parts(parts)
                current_div = Division(
                    number=99,
                    name="PROJECT ADMINISTRATION",
                    cost_per_unit=costs.get("per_unit", 0.0),
                    cost_per_sf=costs.get("per_sf", 0.0),
                    total_cost=costs.get("total", 0.0),
                )
                divisions.append(current_div)
                continue

            # Check for cost code line items (e.g., "20-1000-1000")
            cost_code_match = re.search(
                r"(\d{2}-\d{4}-\d{4})", joined
            )
            if cost_code_match and current_div is not None:
                cost_code = cost_code_match.group(1)
                # Find description - it follows the cost code
                desc_start = joined.index(cost_code) + len(cost_code)
                remaining = joined[desc_start:].strip()

                # Extract description (text before first $ sign)
                desc_match = re.match(r"([^$]+)", remaining)
                description = desc_match.group(1).strip() if desc_match else ""

                # Clean up percentage from description
                pct = _parse_percentage(description)
                description = re.sub(r"\d+\.?\d*\s*%", "", description).strip()

                # Extract costs
                costs = self._extract_costs_from_parts(parts)

                # Extract notes (text after the last dollar amount)
                notes = ""
                dollar_positions = [
                    i for i, p in enumerate(parts) if "$" in p
                ]
                if dollar_positions:
                    last_dollar = max(dollar_positions)
                    note_parts = [
                        p
                        for i, p in enumerate(parts)
                        if i > last_dollar and not p.startswith("$")
                    ]
                    notes = " ".join(note_parts)

                line_item = CostLineItem(
                    cost_code=cost_code,
                    description=description,
                    division_number=current_div.number,
                    division_name=current_div.name,
                    total_cost=costs.get("total", 0.0),
                    cost_per_sf=costs.get("per_sf", 0.0),
                    cost_per_unit=costs.get("per_unit", 0.0),
                    notes=notes,
                    is_percentage_based=pct is not None,
                    percentage=pct,
                )
                current_div.line_items.append(line_item)
                continue

            # Check for admin line items (75-1000-XXXX)
            if current_div and current_div.number == 99:
                admin_match = re.search(r"(75-\d{4}-\d{4})", joined)
                if admin_match:
                    cost_code = admin_match.group(1)
                    remaining = joined[
                        joined.index(cost_code) + len(cost_code) :
                    ].strip()
                    desc_match = re.match(r"([^$%]+)", remaining)
                    description = (
                        desc_match.group(1).strip() if desc_match else ""
                    )
                    pct = _parse_percentage(joined)
                    costs = self._extract_costs_from_parts(parts)

                    line_item = CostLineItem(
                        cost_code=cost_code,
                        description=description,
                        division_number=99,
                        division_name="PROJECT ADMINISTRATION",
                        total_cost=costs.get("total", 0.0),
                        cost_per_sf=costs.get("per_sf", 0.0),
                        cost_per_unit=costs.get("per_unit", 0.0),
                        is_percentage_based=pct is not None,
                        percentage=pct,
                    )
                    current_div.line_items.append(line_item)

        return divisions

    def _extract_costs_from_parts(
        self, parts: list[str]
    ) -> dict[str, float]:
        """Extract per_unit, per_sf, and total costs from tab-separated parts.

        In the estimator format, dollar amounts appear as:
        $   per_unit   $   per_sf   $   total
        """
        dollar_values = []
        for p in parts:
            if "$" in p:
                dollar_values.append(_parse_currency(p))

        result = {}
        if len(dollar_values) >= 3:
            result["per_unit"] = dollar_values[0]
            result["per_sf"] = dollar_values[1]
            result["total"] = dollar_values[2]
        elif len(dollar_values) == 2:
            result["per_sf"] = dollar_values[0]
            result["total"] = dollar_values[1]
        elif len(dollar_values) == 1:
            result["total"] = dollar_values[0]

        return result

    def _extract_number(self, parts: list[str]) -> float:
        """Extract the last numeric value from a list of parts."""
        for p in reversed(parts):
            cleaned = p.replace(",", "").replace("$", "").replace("-", "").strip()
            if cleaned == "0":
                return 0.0
            try:
                return float(cleaned)
            except ValueError:
                continue
        return 0.0

    def _calculate_totals(self, project: Project) -> None:
        """Calculate project totals from divisions."""
        subtotal = 0.0
        admin_total = 0.0

        for div in project.divisions:
            if div.number == 99:
                admin_total = div.total_cost
                # Extract percentages
                for item in div.line_items:
                    if item.percentage:
                        if "fee" in item.description.lower():
                            project.gc_fee_pct = item.percentage
                        elif "bond" in item.description.lower():
                            project.bonding_pct = item.percentage
                        elif "admin" in item.description.lower():
                            project.admin_pct = item.percentage
            else:
                subtotal += div.total_cost

        project.project_subtotal = subtotal
        project.admin_total = admin_total
        project.project_total = subtotal + admin_total

        if project.gba > 0:
            project.cost_per_sf = project.project_total / project.gba
        if project.total_units > 0:
            project.cost_per_unit = project.project_total / project.total_units


def source_file_name(source_file: str) -> str:
    """Extract a project name from a source filename."""
    name = source_file.replace(".xlsx", "").replace(".xls", "")
    # Remove common prefixes
    for prefix in [
        "Construction Cost Estimator - ",
        "Copy of LV Construction Cost Estimator - ",
        "LV Construction Cost Estimator - ",
    ]:
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return name.strip()

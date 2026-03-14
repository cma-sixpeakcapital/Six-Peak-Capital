"""
Construction cost estimation engine.

Combines three estimation methods:
1. Unit price lookup - applies historical $/SF and $/unit rates
2. Similar project matching - weights estimates from comparable projects
3. Statistical regression - scales costs based on project size relationships

The final estimate blends all three methods based on data availability
and confidence in each approach.
"""

import statistics
from construction_estimator.models import (
    Estimate,
    EstimateDivision,
    EstimateLineItem,
)
from construction_estimator.database import HistoricalDatabase
from construction_estimator.matcher import ProjectMatcher


# Method weights for blending (adjusted based on data availability)
DEFAULT_METHOD_WEIGHTS = {
    "unit_price": 0.40,
    "similar_project": 0.40,
    "regression": 0.20,
}

# Cost codes priced per UNIT (not per SF)
UNIT_BASED_CODES = {
    "53-1000-2000",  # Kitchen & Bath Cabinets
    "53-1000-3000",  # Kitchen & Bath Countertops
    "58-1000-1000",  # Appliances
    "59-1000-2000",  # Window Coverings
    "62-1000-2000",  # Rough Plumbing
    "62-1000-2050",  # Water Heater
    "62-1000-3000",  # Fire Sprinkler
    "63-1000-1000",  # Electrical
}

# HVAC rates by bedroom type
HVAC_RATES = {
    "0BR": 5200, "Studio": 5200, "1BR": 5500, "2BR": 9000, "3BR": 13000,
}

# Which SF area to use per division for SF-based items
# Div 1 no longer exists - split into GC, Contingency, and items moved to Div 2
DIVISION_AREA_MAP = {
    2: "total",      # On-Site Construction (includes old GR items)
    3: "concrete",   # Concrete (podium)
    4: "concrete",   # Masonry
    5: "concrete",   # Metals (structural steel)
    6: "wood",       # Wood and Plastics (framing)
    7: "total",      # Thermal & Moisture
    8: "wood",       # Doors, Windows
    9: "wood",       # Finishes (drywall, paint)
    10: "wood",      # Specialties
    11: "wood",      # Equipment
    12: "wood",      # Furnishings
    13: "total",     # Special Construction
    14: "total",     # Conveying Systems
    15: "total",     # Mechanical
    16: "total",     # Electrical
}

# Old Div 1 cost codes that get moved to On-Site Construction (Div 2)
MOVED_TO_ONSITE = {
    "20-2000-1000", "20-2000-2000", "20-2000-3000", "20-2000-4000",
    "20-2000-5000", "20-2000-6000", "20-2500-1000", "20-3000-1000",
    "20-4000-1000", "20-4000-2000", "20-4000-3000", "20-4000-4000",
    "20-4000-5000", "20-4000-6000", "20-4000-7000", "20-4000-8000",
    "20-4000-9000", "20-5000-1000", "20-6000-1000", "20-8000-1000",
}


class EstimatorEngine:
    """Main estimation engine that combines multiple estimation methods."""

    def __init__(
        self,
        database: HistoricalDatabase,
        method_weights: dict[str, float] | None = None,
    ):
        self.db = database
        self.matcher = ProjectMatcher()
        self.method_weights = method_weights or DEFAULT_METHOD_WEIGHTS

    def estimate(
        self,
        gba: float = 0,           # total, for backward compat
        units: int = 0,
        unit_mix: dict = None,
        construction_type: str = "wood",
        num_floors: int = 5,
        gc_fee_pct: float = 6.0,
        bonding_pct: float = 1.0,
        admin_pct: float = 2.0,
        # New qualifier params
        gba_concrete: float = 0,
        gba_wood: float = 0,
        podium_levels: int = 0,
        wood_levels: int = 4,
        subterranean: bool = False,
        parking_spaces: int = 0,
        elevator_count: int = 1,
        elevator_stops: int = 7,
        lot_size: float = 0,
        shored_area: float = 0,
    ) -> Estimate:
        """Generate a full project estimate.

        Args:
            gba: Gross Building Area in square feet (total)
            units: Number of residential units
            unit_mix: Unit mix, e.g., {"1BR": 50, "2BR": 30}
            construction_type: "wood", "concrete", or "mixed"
            num_floors: Number of floors
            gc_fee_pct: GC fee percentage (default 6%)
            bonding_pct: Bonding percentage (default 1%)
            admin_pct: Administration percentage (default 2%)
            gba_concrete: Concrete area in SF
            gba_wood: Wood area in SF
            podium_levels: Number of podium levels
            wood_levels: Number of wood levels
            subterranean: Whether project has subterranean parking
            parking_spaces: Number of parking spaces
            elevator_count: Number of elevators
            elevator_stops: Number of elevator stops
            lot_size: Lot size in SF
            shored_area: Shored area in SF

        Returns:
            Complete Estimate with division breakdowns and confidence ranges
        """
        if unit_mix is None:
            unit_mix = {}

        # Resolve GBA values
        if gba_concrete > 0 or gba_wood > 0:
            if gba == 0:
                gba = gba_concrete + gba_wood
        else:
            # Backward compat: if only gba provided, assume all wood
            if gba > 0:
                gba_wood = gba

        # Find similar projects
        similar = self.matcher.find_similar(
            self.db.projects,
            target_gba=gba,
            target_units=units,
            target_unit_mix=unit_mix,
            target_construction_type=construction_type,
            target_num_floors=num_floors,
            target_gba_concrete=gba_concrete,
            target_gba_wood=gba_wood,
        )

        # Get all unique divisions across projects
        all_divisions = self._get_all_divisions()

        # Estimate each division (skip Div 1, skip Div 99)
        estimated_divisions = []
        hard_cost_subtotal = 0.0
        low_subtotal = 0.0
        high_subtotal = 0.0

        for div_num, div_name in sorted(all_divisions.items()):
            if div_num == 1:   # Skip Div 1 - split into GC, Contingency, moved items
                continue
            if div_num == 99:  # Skip admin, calculated separately
                continue

            est_div = self._estimate_division(
                div_num, div_name, gba, units, similar,
                unit_mix=unit_mix,
                gba_concrete=gba_concrete,
                gba_wood=gba_wood,
                podium_levels=podium_levels,
                wood_levels=wood_levels,
                elevator_count=elevator_count,
                elevator_stops=elevator_stops,
                shored_area=shored_area,
            )
            estimated_divisions.append(est_div)
            hard_cost_subtotal += est_div.estimated_total
            low_subtotal += est_div.low_total
            high_subtotal += est_div.high_total

        # Contingency = hard_cost_subtotal * 3%
        contingency_total = hard_cost_subtotal * 0.03
        contingency_div = EstimateDivision(
            number=97,
            name="CONTINGENCY",
            estimated_total=contingency_total,
            estimated_per_sf=contingency_total / gba if gba > 0 else 0,
            estimated_per_unit=contingency_total / units if units > 0 else 0,
            low_total=low_subtotal * 0.03,
            high_total=high_subtotal * 0.03,
            line_items=[
                EstimateLineItem(
                    cost_code="97-1000-1000",
                    description="Contingency (3%)",
                    division_number=97,
                    division_name="CONTINGENCY",
                    estimated_total=contingency_total,
                    estimated_per_sf=contingency_total / gba if gba > 0 else 0,
                    estimated_per_unit=contingency_total / units if units > 0 else 0,
                    low_total=low_subtotal * 0.03,
                    high_total=high_subtotal * 0.03,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
            ],
        )
        estimated_divisions.append(contingency_div)

        # General Conditions = (hard_cost_subtotal + contingency) * 6%
        gc_base = hard_cost_subtotal + contingency_total
        general_conditions_total = gc_base * 0.06
        gc_div = EstimateDivision(
            number=98,
            name="GENERAL CONDITIONS",
            estimated_total=general_conditions_total,
            estimated_per_sf=general_conditions_total / gba if gba > 0 else 0,
            estimated_per_unit=general_conditions_total / units if units > 0 else 0,
            low_total=(low_subtotal + low_subtotal * 0.03) * 0.06,
            high_total=(high_subtotal + high_subtotal * 0.03) * 0.06,
            line_items=[
                EstimateLineItem(
                    cost_code="98-1000-1000",
                    description="General Conditions (6%)",
                    division_number=98,
                    division_name="GENERAL CONDITIONS",
                    estimated_total=general_conditions_total,
                    estimated_per_sf=general_conditions_total / gba if gba > 0 else 0,
                    estimated_per_unit=general_conditions_total / units if units > 0 else 0,
                    low_total=(low_subtotal + low_subtotal * 0.03) * 0.06,
                    high_total=(high_subtotal + high_subtotal * 0.03) * 0.06,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
            ],
        )
        estimated_divisions.append(gc_div)

        # Project Subtotal
        project_subtotal = hard_cost_subtotal + contingency_total + general_conditions_total

        # GC Fee, Bonding, Admin on project_subtotal
        gc_fee = project_subtotal * (gc_fee_pct / 100)
        bonding = project_subtotal * (bonding_pct / 100)
        admin = project_subtotal * (admin_pct / 100)
        admin_total = gc_fee + bonding + admin

        low_project_subtotal = low_subtotal + low_subtotal * 0.03 + (low_subtotal + low_subtotal * 0.03) * 0.06
        high_project_subtotal = high_subtotal + high_subtotal * 0.03 + (high_subtotal + high_subtotal * 0.03) * 0.06

        admin_div = EstimateDivision(
            number=99,
            name="PROJECT ADMINISTRATION",
            estimated_total=admin_total,
            estimated_per_sf=admin_total / gba if gba > 0 else 0,
            estimated_per_unit=admin_total / units if units > 0 else 0,
            low_total=low_project_subtotal * (gc_fee_pct + bonding_pct + admin_pct) / 100,
            high_total=high_project_subtotal * (gc_fee_pct + bonding_pct + admin_pct) / 100,
            line_items=[
                EstimateLineItem(
                    cost_code="75-1000-1000",
                    description=f"GC Fee ({gc_fee_pct}%)",
                    division_number=99,
                    division_name="PROJECT ADMINISTRATION",
                    estimated_total=gc_fee,
                    estimated_per_sf=gc_fee / gba if gba > 0 else 0,
                    estimated_per_unit=gc_fee / units if units > 0 else 0,
                    low_total=low_project_subtotal * gc_fee_pct / 100,
                    high_total=high_project_subtotal * gc_fee_pct / 100,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
                EstimateLineItem(
                    cost_code="75-1000-2000",
                    description=f"Bonding ({bonding_pct}%)",
                    division_number=99,
                    division_name="PROJECT ADMINISTRATION",
                    estimated_total=bonding,
                    estimated_per_sf=bonding / gba if gba > 0 else 0,
                    estimated_per_unit=bonding / units if units > 0 else 0,
                    low_total=low_project_subtotal * bonding_pct / 100,
                    high_total=high_project_subtotal * bonding_pct / 100,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
                EstimateLineItem(
                    cost_code="75-1000-3000",
                    description=f"Administration ({admin_pct}%)",
                    division_number=99,
                    division_name="PROJECT ADMINISTRATION",
                    estimated_total=admin,
                    estimated_per_sf=admin / gba if gba > 0 else 0,
                    estimated_per_unit=admin / units if units > 0 else 0,
                    low_total=low_project_subtotal * admin_pct / 100,
                    high_total=high_project_subtotal * admin_pct / 100,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
            ],
        )
        estimated_divisions.append(admin_div)

        project_total = project_subtotal + admin_total
        low_total = low_project_subtotal + admin_div.low_total
        high_total = high_project_subtotal + admin_div.high_total

        return Estimate(
            target_gba=gba,
            target_units=units,
            target_unit_mix=unit_mix,
            target_construction_type=construction_type,
            divisions=estimated_divisions,
            project_subtotal=project_subtotal,
            admin_total=admin_total,
            project_total=project_total,
            cost_per_sf=project_total / gba if gba > 0 else 0,
            cost_per_unit=project_total / units if units > 0 else 0,
            low_total=low_total,
            high_total=high_total,
            similar_projects=[p.name for p, _ in similar[:3]],
            match_scores=[s for _, s in similar[:3]],
        )

    def _get_effective_gba(self, div_num, gba_concrete, gba_wood):
        """Get the effective GBA for a division based on its area type."""
        area_type = DIVISION_AREA_MAP.get(div_num, "total")
        total = gba_concrete + gba_wood
        if area_type == "concrete" and gba_concrete > 0:
            return gba_concrete
        elif area_type == "wood" and gba_wood > 0:
            return gba_wood
        return total if total > 0 else 1  # avoid division by zero

    def _get_all_divisions(self) -> dict[int, str]:
        """Get all division numbers and names from the database."""
        divisions = {}
        for project in self.db.projects:
            for div in project.divisions:
                if div.number not in divisions:
                    divisions[div.number] = div.name
        return divisions

    def _estimate_division(
        self,
        div_num: int,
        div_name: str,
        gba: float,
        units: int,
        similar: list,
        unit_mix: dict = None,
        gba_concrete: float = 0,
        gba_wood: float = 0,
        podium_levels: int = 0,
        wood_levels: int = 4,
        elevator_count: int = 1,
        elevator_stops: int = 7,
        shored_area: float = 0,
    ) -> EstimateDivision:
        """Estimate costs for a single division using blended methods."""
        effective_gba = self._get_effective_gba(div_num, gba_concrete, gba_wood)

        # Method 1: Unit price from database stats
        div_stats = self.db.get_division_stats(div_num)
        unit_price_total = div_stats["median_per_sf"] * effective_gba

        # Method 2: Similar project weighted average
        similar_total = self._similar_project_estimate(
            div_num, effective_gba, units, similar
        )

        # Method 3: Regression (scale by GBA ratio from mean)
        regression_total = self._regression_estimate(
            div_num, effective_gba, units
        )

        # Blend methods based on data availability
        estimates = []
        weights = []

        if div_stats["data_points"] > 0:
            estimates.append(unit_price_total)
            weights.append(self.method_weights["unit_price"])

        if similar_total > 0:
            estimates.append(similar_total)
            weights.append(self.method_weights["similar_project"])

        if regression_total > 0:
            estimates.append(regression_total)
            weights.append(self.method_weights["regression"])

        if not estimates:
            estimated_total = 0.0
        else:
            # Normalize weights
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]
            estimated_total = sum(
                e * w for e, w in zip(estimates, weights)
            )

        # Confidence range from historical spread
        low = div_stats["p25_per_sf"] * effective_gba if div_stats["data_points"] > 0 else estimated_total * 0.85
        high = div_stats["p75_per_sf"] * effective_gba if div_stats["data_points"] > 0 else estimated_total * 1.15

        # Estimate line items within this division
        line_items = self._estimate_line_items(
            div_num, div_name, gba, units, similar,
            unit_mix=unit_mix or {},
            gba_concrete=gba_concrete,
            gba_wood=gba_wood,
            podium_levels=podium_levels,
            wood_levels=wood_levels,
            elevator_count=elevator_count,
            elevator_stops=elevator_stops,
            shored_area=shored_area,
        )

        return EstimateDivision(
            number=div_num,
            name=div_name,
            estimated_total=estimated_total,
            estimated_per_sf=estimated_total / gba if gba > 0 else 0,
            estimated_per_unit=estimated_total / units if units > 0 else 0,
            low_total=low,
            high_total=high,
            line_items=line_items,
        )

    def _similar_project_estimate(
        self,
        div_num: int,
        gba: float,
        units: int,
        similar: list,
    ) -> float:
        """Estimate division cost from similar projects (weighted by similarity)."""
        weighted_sum = 0.0
        total_weight = 0.0

        for project, score in similar:
            for div in project.divisions:
                if div.number == div_num and div.total_cost > 0:
                    # Scale the similar project's cost to our target GBA
                    if project.gba > 0:
                        scaled_cost = div.cost_per_sf * gba
                    else:
                        scaled_cost = div.cost_per_unit * units
                    weighted_sum += scaled_cost * score
                    total_weight += score
                    break

        if total_weight > 0:
            return weighted_sum / total_weight
        return 0.0

    def _regression_estimate(
        self, div_num: int, gba: float, units: int
    ) -> float:
        """Simple linear scaling estimate based on $/SF trends."""
        entries = self.db._division_index.get(div_num, [])
        active = [e for e in entries if e["total"] > 0]

        if len(active) < 2:
            return 0.0

        # Use median $/SF as the base rate
        per_sf_values = [e["per_sf"] for e in active]
        median_per_sf = statistics.median(per_sf_values)

        return median_per_sf * gba

    def _estimate_line_items(
        self,
        div_num: int,
        div_name: str,
        gba: float,
        units: int,
        similar: list,
        unit_mix: dict = None,
        gba_concrete: float = 0,
        gba_wood: float = 0,
        podium_levels: int = 0,
        wood_levels: int = 4,
        elevator_count: int = 1,
        elevator_stops: int = 7,
        shored_area: float = 0,
    ) -> list[EstimateLineItem]:
        """Estimate individual line items within a division."""
        if unit_mix is None:
            unit_mix = {}

        effective_gba = self._get_effective_gba(div_num, gba_concrete, gba_wood)
        total_floors = podium_levels + wood_levels

        # Collect all cost codes for this division
        cost_codes = set()
        for project in self.db.projects:
            for div in project.divisions:
                if div.number == div_num:
                    for item in div.line_items:
                        cost_codes.add(
                            (item.cost_code, item.description)
                        )

        line_items = []
        for cost_code, description in sorted(cost_codes):
            stats = self.db.get_cost_code_stats(cost_code)

            if stats["data_points"] == 0:
                continue

            # Determine estimation method based on cost code
            if cost_code == "62-1000-1000":
                # HVAC: use HVAC_RATES x unit_mix counts
                estimated_total = 0.0
                for br_type, count in unit_mix.items():
                    rate = HVAC_RATES.get(br_type, 5500)
                    estimated_total += rate * count
                method = "hvac_rates"
            elif cost_code == "61-1000-4000":
                # Elevator
                estimated_total = elevator_count * elevator_stops * 31400
                method = "elevator_calc"
            elif cost_code == "61-1000-2000":
                # Construction Elevator
                if total_floors >= 5:
                    estimated_total = elevator_count * 200000
                else:
                    estimated_total = 0
                method = "construction_elevator"
            elif cost_code == "40-2000-8000":
                # Shoring
                estimated_total = shored_area * 96
                method = "shoring_calc"
            elif cost_code == "50-1000-1000":
                # Structural Concrete
                estimated_total = gba_concrete * 45
                method = "structural_concrete"
            elif cost_code in UNIT_BASED_CODES:
                # Per-unit pricing
                estimated_total = stats["median_per_unit"] * units
                method = "per_unit"
            else:
                # Standard per-SF pricing using effective GBA
                estimated_total = stats["median_per_sf"] * effective_gba
                method = "per_sf"

            # Compute per-sf and per-unit rates
            estimated_per_sf = estimated_total / gba if gba > 0 else 0
            estimated_per_unit = estimated_total / units if units > 0 else 0

            # Confidence based on number of data points and spread
            confidence = min(1.0, stats["data_points"] / 5.0)
            if stats["mean_per_sf"] > 0:
                spread = (
                    stats["p75_per_sf"] - stats["p25_per_sf"]
                ) / stats["mean_per_sf"]
                confidence *= max(0.3, 1.0 - spread)

            low = stats["p25_per_sf"] * effective_gba
            high = stats["p75_per_sf"] * effective_gba

            line_items.append(
                EstimateLineItem(
                    cost_code=cost_code,
                    description=description,
                    division_number=div_num,
                    division_name=div_name,
                    estimated_total=estimated_total,
                    estimated_per_sf=estimated_per_sf,
                    estimated_per_unit=estimated_per_unit,
                    low_total=low,
                    high_total=high,
                    confidence=confidence,
                    data_points=stats["data_points"],
                    method=method,
                )
            )

        return line_items

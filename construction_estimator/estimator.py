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
        gba: float,
        units: int,
        unit_mix: dict[str, int],
        construction_type: str = "wood",
        num_floors: int = 5,
        gc_fee_pct: float = 6.0,
        bonding_pct: float = 1.0,
        admin_pct: float = 2.0,
    ) -> Estimate:
        """Generate a full project estimate.

        Args:
            gba: Gross Building Area in square feet
            units: Number of residential units
            unit_mix: Unit mix, e.g., {"1BR": 50, "2BR": 30}
            construction_type: "wood", "concrete", or "mixed"
            num_floors: Number of floors
            gc_fee_pct: GC fee percentage (default 6%)
            bonding_pct: Bonding percentage (default 1%)
            admin_pct: Administration percentage (default 2%)

        Returns:
            Complete Estimate with division breakdowns and confidence ranges
        """
        # Find similar projects
        similar = self.matcher.find_similar(
            self.db.projects,
            target_gba=gba,
            target_units=units,
            target_unit_mix=unit_mix,
            target_construction_type=construction_type,
            target_num_floors=num_floors,
        )

        # Get all unique divisions across projects
        all_divisions = self._get_all_divisions()

        # Estimate each division
        estimated_divisions = []
        project_subtotal = 0.0
        low_subtotal = 0.0
        high_subtotal = 0.0

        for div_num, div_name in sorted(all_divisions.items()):
            if div_num == 99:  # Skip admin, calculated separately
                continue

            est_div = self._estimate_division(
                div_num, div_name, gba, units, similar
            )
            estimated_divisions.append(est_div)
            project_subtotal += est_div.estimated_total
            low_subtotal += est_div.low_total
            high_subtotal += est_div.high_total

        # Calculate project administration
        admin_fee = project_subtotal * (gc_fee_pct / 100)
        bonding = project_subtotal * (bonding_pct / 100)
        admin = project_subtotal * (admin_pct / 100)
        admin_total = admin_fee + bonding + admin

        admin_div = EstimateDivision(
            number=99,
            name="PROJECT ADMINISTRATION",
            estimated_total=admin_total,
            estimated_per_sf=admin_total / gba if gba > 0 else 0,
            estimated_per_unit=admin_total / units if units > 0 else 0,
            low_total=low_subtotal * (gc_fee_pct + bonding_pct + admin_pct) / 100,
            high_total=high_subtotal * (gc_fee_pct + bonding_pct + admin_pct) / 100,
            line_items=[
                EstimateLineItem(
                    cost_code="75-1000-1000",
                    description=f"GC Fee ({gc_fee_pct}%)",
                    division_number=99,
                    division_name="PROJECT ADMINISTRATION",
                    estimated_total=admin_fee,
                    estimated_per_sf=admin_fee / gba if gba > 0 else 0,
                    estimated_per_unit=admin_fee / units if units > 0 else 0,
                    low_total=low_subtotal * gc_fee_pct / 100,
                    high_total=high_subtotal * gc_fee_pct / 100,
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
                    low_total=low_subtotal * bonding_pct / 100,
                    high_total=high_subtotal * bonding_pct / 100,
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
                    low_total=low_subtotal * admin_pct / 100,
                    high_total=high_subtotal * admin_pct / 100,
                    confidence=1.0,
                    data_points=self.db.project_count,
                    method="percentage",
                ),
            ],
        )
        estimated_divisions.append(admin_div)

        project_total = project_subtotal + admin_total
        low_total = low_subtotal + admin_div.low_total
        high_total = high_subtotal + admin_div.high_total

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
    ) -> EstimateDivision:
        """Estimate costs for a single division using blended methods."""
        # Method 1: Unit price from database stats
        div_stats = self.db.get_division_stats(div_num)
        unit_price_total = div_stats["median_per_sf"] * gba

        # Method 2: Similar project weighted average
        similar_total = self._similar_project_estimate(
            div_num, gba, units, similar
        )

        # Method 3: Regression (scale by GBA ratio from mean)
        regression_total = self._regression_estimate(
            div_num, gba, units
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
        low = div_stats["p25_per_sf"] * gba if div_stats["data_points"] > 0 else estimated_total * 0.85
        high = div_stats["p75_per_sf"] * gba if div_stats["data_points"] > 0 else estimated_total * 1.15

        # Estimate line items within this division
        line_items = self._estimate_line_items(
            div_num, div_name, gba, units, similar
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
    ) -> list[EstimateLineItem]:
        """Estimate individual line items within a division."""
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

            # Check if this is a per-unit or per-SF item
            # Items like appliances, cabinets are per-unit
            entries = self.db._cost_code_index.get(cost_code, [])
            is_per_unit = any(
                e.get("is_percentage_based") for e in entries
            )

            # Use median rates
            estimated_per_sf = stats["median_per_sf"]
            estimated_per_unit = stats["median_per_unit"]
            estimated_total = estimated_per_sf * gba

            # Confidence based on number of data points and spread
            confidence = min(1.0, stats["data_points"] / 5.0)
            if stats["mean_per_sf"] > 0:
                spread = (
                    stats["p75_per_sf"] - stats["p25_per_sf"]
                ) / stats["mean_per_sf"]
                confidence *= max(0.3, 1.0 - spread)

            low = stats["p25_per_sf"] * gba
            high = stats["p75_per_sf"] * gba

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
                    method="blended",
                )
            )

        return line_items

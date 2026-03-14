"""Data models for the construction estimator."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CostLineItem:
    """A single cost line item from an estimator spreadsheet."""

    cost_code: str  # e.g., "20-1000-1000"
    description: str  # e.g., "Field Supervision"
    division_number: int  # e.g., 1
    division_name: str  # e.g., "GENERAL REQUIREMENTS"
    total_cost: float
    cost_per_sf: float
    cost_per_unit: float
    notes: str = ""
    is_percentage_based: bool = False
    percentage: Optional[float] = None  # e.g., 6.0 for "6%"


@dataclass
class Division:
    """A CSI division with its line items."""

    number: int
    name: str  # e.g., "GENERAL REQUIREMENTS"
    total_cost: float
    cost_per_sf: float
    cost_per_unit: float
    line_items: list[CostLineItem] = field(default_factory=list)
    notes: str = ""


@dataclass
class Project:
    """A historical project with its full cost breakdown."""

    name: str  # e.g., "11218 Califa"
    address: str
    lot_size: float
    gba: float  # Gross Building Area
    gba_concrete: float  # Type 1 area
    gba_wood: float  # Type 3A area
    total_units: int
    unit_mix: dict[str, int]  # e.g., {"Studio": 0, "1BR": 46, "2BR": 30}
    floor_areas: dict[str, float]  # e.g., {"1st Floor": 8752, ...}
    num_floors: int
    divisions: list[Division] = field(default_factory=list)
    project_total: float = 0.0
    project_subtotal: float = 0.0  # before admin
    admin_total: float = 0.0
    gc_fee_pct: float = 0.0
    bonding_pct: float = 0.0
    admin_pct: float = 0.0
    cost_per_sf: float = 0.0
    cost_per_unit: float = 0.0
    source_file: str = ""
    source_file_id: str = ""  # Box file ID

    @property
    def construction_type(self) -> str:
        if self.gba_concrete > 0 and self.gba_wood > 0:
            return "mixed"
        elif self.gba_concrete > 0:
            return "concrete"
        return "wood"

    @property
    def avg_unit_size(self) -> float:
        if self.total_units == 0:
            return 0.0
        return self.gba / self.total_units


@dataclass
class EstimateLineItem:
    """A single estimated cost line item with confidence range."""

    cost_code: str
    description: str
    division_number: int
    division_name: str
    estimated_total: float
    estimated_per_sf: float
    estimated_per_unit: float
    low_total: float  # 25th percentile
    high_total: float  # 75th percentile
    confidence: float  # 0-1, based on number of data points
    data_points: int  # how many historical projects had this line item
    method: str  # "unit_price", "regression", "similar_project"
    notes: str = ""


@dataclass
class EstimateDivision:
    """An estimated division with its line items."""

    number: int
    name: str
    estimated_total: float
    estimated_per_sf: float
    estimated_per_unit: float
    low_total: float
    high_total: float
    line_items: list[EstimateLineItem] = field(default_factory=list)


@dataclass
class Estimate:
    """A complete project estimate."""

    # Target project parameters
    target_gba: float
    target_units: int
    target_unit_mix: dict[str, int]
    target_construction_type: str

    # Results
    divisions: list[EstimateDivision] = field(default_factory=list)
    project_subtotal: float = 0.0
    admin_total: float = 0.0
    project_total: float = 0.0
    cost_per_sf: float = 0.0
    cost_per_unit: float = 0.0
    low_total: float = 0.0
    high_total: float = 0.0

    # Similar projects used
    similar_projects: list[str] = field(default_factory=list)
    match_scores: list[float] = field(default_factory=list)

    def summary(self) -> str:
        """Return a formatted summary of the estimate."""
        lines = []
        lines.append("=" * 80)
        lines.append("CONSTRUCTION COST ESTIMATE")
        lines.append("=" * 80)
        lines.append(
            f"Target: {self.target_gba:,.0f} SF | "
            f"{self.target_units} Units | "
            f"{self.target_construction_type.title()} Construction"
        )
        lines.append(f"Unit Mix: {self.target_unit_mix}")
        lines.append("-" * 80)
        lines.append(
            f"{'Category':<45} {'Total':>12} {'$/SF':>8} {'$/Unit':>10}"
        )
        lines.append("-" * 80)

        for div in self.divisions:
            lines.append(
                f"Div. {div.number:<2} - {div.name:<37} "
                f"${div.estimated_total:>11,.0f} "
                f"${div.estimated_per_sf:>6,.2f} "
                f"${div.estimated_per_unit:>8,.0f}"
            )

        lines.append("-" * 80)
        lines.append(
            f"{'Project Subtotal':<45} "
            f"${self.project_subtotal:>11,.0f} "
            f"${self.project_subtotal / self.target_gba:>6,.2f} "
            f"${self.project_subtotal / self.target_units:>8,.0f}"
        )
        lines.append(
            f"{'Project Administration':<45} "
            f"${self.admin_total:>11,.0f} "
            f"${self.admin_total / self.target_gba:>6,.2f} "
            f"${self.admin_total / self.target_units:>8,.0f}"
        )
        lines.append("=" * 80)
        lines.append(
            f"{'PROJECT TOTAL':<45} "
            f"${self.project_total:>11,.0f} "
            f"${self.cost_per_sf:>6,.2f} "
            f"${self.cost_per_unit:>8,.0f}"
        )
        lines.append(
            f"{'Confidence Range':<45} "
            f"${self.low_total:>11,.0f} - ${self.high_total:>11,.0f}"
        )
        lines.append("=" * 80)

        if self.similar_projects:
            lines.append("\nBased on similar projects:")
            for name, score in zip(self.similar_projects, self.match_scores):
                lines.append(f"  - {name} (similarity: {score:.0%})")

        return "\n".join(lines)

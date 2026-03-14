"""
Historical cost database built from parsed project data.

Stores normalized unit prices across all historical projects and provides
statistical lookups (mean, median, percentiles) by cost code and division.
"""

import json
import statistics
from pathlib import Path
from construction_estimator.models import Project, CostLineItem, Division
from construction_estimator.parser import EstimatorParser


class HistoricalDatabase:
    """In-memory database of historical construction costs.

    Stores projects and provides statistical cost lookups by:
    - Cost code (e.g., "20-1000-1000" for Field Supervision)
    - Division (e.g., Div. 6 - Wood and Plastics)
    - Project-level metrics ($/SF, $/unit)
    """

    def __init__(self):
        self.projects: list[Project] = []
        self._parser = EstimatorParser()

        # Indexed cost data for fast lookups
        # cost_code -> list of {per_sf, per_unit, total, project_name, gba, units}
        self._cost_code_index: dict[str, list[dict]] = {}
        # division_number -> list of {per_sf, per_unit, total, ...}
        self._division_index: dict[int, list[dict]] = {}

    @property
    def project_count(self) -> int:
        return len(self.projects)

    def add_project_from_text(
        self,
        content: str,
        source_file: str = "",
        source_file_id: str = "",
    ) -> Project:
        """Parse text content and add the project to the database.

        Args:
            content: Raw text from Box get_file_content
            source_file: Original filename
            source_file_id: Box file ID

        Returns:
            The parsed Project
        """
        project = self._parser.parse_text_content(
            content, source_file, source_file_id
        )
        self.add_project(project)
        return project

    def add_project(self, project: Project) -> None:
        """Add a parsed project to the database and update indexes."""
        self.projects.append(project)
        self._index_project(project)

    def _index_project(self, project: Project) -> None:
        """Index a project's costs for fast statistical lookups."""
        for div in project.divisions:
            # Index division totals
            if div.number not in self._division_index:
                self._division_index[div.number] = []

            self._division_index[div.number].append(
                {
                    "per_sf": div.cost_per_sf,
                    "per_unit": div.cost_per_unit,
                    "total": div.total_cost,
                    "project_name": project.name,
                    "gba": project.gba,
                    "units": project.total_units,
                    "gba_concrete": project.gba_concrete,
                    "gba_wood": project.gba_wood,
                }
            )

            # Index line items
            for item in div.line_items:
                if item.cost_code not in self._cost_code_index:
                    self._cost_code_index[item.cost_code] = []

                self._cost_code_index[item.cost_code].append(
                    {
                        "per_sf": item.cost_per_sf,
                        "per_unit": item.cost_per_unit,
                        "total": item.total_cost,
                        "description": item.description,
                        "project_name": project.name,
                        "gba": project.gba,
                        "units": project.total_units,
                        "is_percentage_based": item.is_percentage_based,
                        "percentage": item.percentage,
                        "notes": item.notes,
                        "gba_concrete": project.gba_concrete,
                        "gba_wood": project.gba_wood,
                    }
                )

    def get_cost_code_stats(
        self, cost_code: str, exclude_zeros: bool = True
    ) -> dict:
        """Get statistical summary for a cost code across all projects.

        Returns:
            Dict with keys: mean_per_sf, median_per_sf, p25_per_sf, p75_per_sf,
            mean_per_unit, median_per_unit, p25_per_unit, p75_per_unit,
            data_points, description
        """
        entries = self._cost_code_index.get(cost_code, [])
        if exclude_zeros:
            entries = [e for e in entries if e["total"] > 0]

        if not entries:
            return {
                "mean_per_sf": 0.0,
                "median_per_sf": 0.0,
                "p25_per_sf": 0.0,
                "p75_per_sf": 0.0,
                "mean_per_unit": 0.0,
                "median_per_unit": 0.0,
                "p25_per_unit": 0.0,
                "p75_per_unit": 0.0,
                "data_points": 0,
                "description": "",
            }

        per_sf = [e["per_sf"] for e in entries]
        per_unit = [e["per_unit"] for e in entries]
        description = entries[0].get("description", "")

        return {
            "mean_per_sf": statistics.mean(per_sf),
            "median_per_sf": statistics.median(per_sf),
            "p25_per_sf": _percentile(per_sf, 25),
            "p75_per_sf": _percentile(per_sf, 75),
            "mean_per_unit": statistics.mean(per_unit),
            "median_per_unit": statistics.median(per_unit),
            "p25_per_unit": _percentile(per_unit, 25),
            "p75_per_unit": _percentile(per_unit, 75),
            "data_points": len(entries),
            "description": description,
        }

    def get_division_stats(
        self, division_number: int, exclude_zeros: bool = True
    ) -> dict:
        """Get statistical summary for a division across all projects."""
        entries = self._division_index.get(division_number, [])
        if exclude_zeros:
            entries = [e for e in entries if e["total"] > 0]

        if not entries:
            return {
                "mean_per_sf": 0.0,
                "median_per_sf": 0.0,
                "p25_per_sf": 0.0,
                "p75_per_sf": 0.0,
                "mean_per_unit": 0.0,
                "median_per_unit": 0.0,
                "p25_per_unit": 0.0,
                "p75_per_unit": 0.0,
                "data_points": 0,
            }

        per_sf = [e["per_sf"] for e in entries]
        per_unit = [e["per_unit"] for e in entries]

        return {
            "mean_per_sf": statistics.mean(per_sf),
            "median_per_sf": statistics.median(per_sf),
            "p25_per_sf": _percentile(per_sf, 25),
            "p75_per_sf": _percentile(per_sf, 75),
            "mean_per_unit": statistics.mean(per_unit),
            "median_per_unit": statistics.median(per_unit),
            "p25_per_unit": _percentile(per_unit, 25),
            "p75_per_unit": _percentile(per_unit, 75),
            "data_points": len(entries),
        }

    def get_all_cost_codes(self) -> list[str]:
        """Return all known cost codes sorted."""
        return sorted(self._cost_code_index.keys())

    def get_project_totals_per_sf(self) -> list[float]:
        """Return project total $/SF for all projects."""
        return [p.cost_per_sf for p in self.projects if p.cost_per_sf > 0]

    def get_project_totals_per_unit(self) -> list[float]:
        """Return project total $/unit for all projects."""
        return [
            p.cost_per_unit for p in self.projects if p.cost_per_unit > 0
        ]

    def save(self, path: str) -> None:
        """Save the database to a JSON file for reuse."""
        data = {
            "version": "1.0",
            "projects": [],
        }
        for p in self.projects:
            proj_data = {
                "name": p.name,
                "address": p.address,
                "lot_size": p.lot_size,
                "gba": p.gba,
                "gba_concrete": p.gba_concrete,
                "gba_wood": p.gba_wood,
                "total_units": p.total_units,
                "unit_mix": p.unit_mix,
                "floor_areas": p.floor_areas,
                "num_floors": p.num_floors,
                "project_total": p.project_total,
                "project_subtotal": p.project_subtotal,
                "admin_total": p.admin_total,
                "gc_fee_pct": p.gc_fee_pct,
                "bonding_pct": p.bonding_pct,
                "admin_pct": p.admin_pct,
                "cost_per_sf": p.cost_per_sf,
                "cost_per_unit": p.cost_per_unit,
                "source_file": p.source_file,
                "source_file_id": p.source_file_id,
                "podium_levels": p.podium_levels,
                "wood_levels": p.wood_levels,
                "subterranean": p.subterranean,
                "parking_spaces": p.parking_spaces,
                "elevator_count": p.elevator_count,
                "elevator_stops": p.elevator_stops,
                "lot_size_sf": p.lot_size_sf,
                "shored_area": p.shored_area,
                "divisions": [],
            }
            for div in p.divisions:
                div_data = {
                    "number": div.number,
                    "name": div.name,
                    "total_cost": div.total_cost,
                    "cost_per_sf": div.cost_per_sf,
                    "cost_per_unit": div.cost_per_unit,
                    "line_items": [
                        {
                            "cost_code": li.cost_code,
                            "description": li.description,
                            "total_cost": li.total_cost,
                            "cost_per_sf": li.cost_per_sf,
                            "cost_per_unit": li.cost_per_unit,
                            "notes": li.notes,
                            "is_percentage_based": li.is_percentage_based,
                            "percentage": li.percentage,
                        }
                        for li in div.line_items
                    ],
                }
                proj_data["divisions"].append(div_data)
            data["projects"].append(proj_data)

        Path(path).write_text(json.dumps(data, indent=2))

    def load(self, path: str) -> None:
        """Load a previously saved database from JSON."""
        data = json.loads(Path(path).read_text())

        for proj_data in data["projects"]:
            divisions = []
            for div_data in proj_data["divisions"]:
                line_items = [
                    CostLineItem(
                        cost_code=li["cost_code"],
                        description=li["description"],
                        division_number=div_data["number"],
                        division_name=div_data["name"],
                        total_cost=li["total_cost"],
                        cost_per_sf=li["cost_per_sf"],
                        cost_per_unit=li["cost_per_unit"],
                        notes=li.get("notes", ""),
                        is_percentage_based=li.get(
                            "is_percentage_based", False
                        ),
                        percentage=li.get("percentage"),
                    )
                    for li in div_data["line_items"]
                ]
                divisions.append(
                    Division(
                        number=div_data["number"],
                        name=div_data["name"],
                        total_cost=div_data["total_cost"],
                        cost_per_sf=div_data["cost_per_sf"],
                        cost_per_unit=div_data["cost_per_unit"],
                        line_items=line_items,
                    )
                )

            project = Project(
                name=proj_data["name"],
                address=proj_data["address"],
                lot_size=proj_data["lot_size"],
                gba=proj_data["gba"],
                gba_concrete=proj_data["gba_concrete"],
                gba_wood=proj_data["gba_wood"],
                total_units=proj_data["total_units"],
                unit_mix=proj_data["unit_mix"],
                floor_areas=proj_data["floor_areas"],
                num_floors=proj_data["num_floors"],
                divisions=divisions,
                project_total=proj_data["project_total"],
                project_subtotal=proj_data["project_subtotal"],
                admin_total=proj_data["admin_total"],
                gc_fee_pct=proj_data["gc_fee_pct"],
                bonding_pct=proj_data["bonding_pct"],
                admin_pct=proj_data["admin_pct"],
                cost_per_sf=proj_data["cost_per_sf"],
                cost_per_unit=proj_data["cost_per_unit"],
                source_file=proj_data["source_file"],
                source_file_id=proj_data.get("source_file_id", ""),
                podium_levels=proj_data.get("podium_levels", 0),
                wood_levels=proj_data.get("wood_levels", 0),
                subterranean=proj_data.get("subterranean", False),
                parking_spaces=proj_data.get("parking_spaces", 0),
                elevator_count=proj_data.get("elevator_count", 1),
                elevator_stops=proj_data.get("elevator_stops", 0),
                lot_size_sf=proj_data.get("lot_size_sf", 0.0),
                shored_area=proj_data.get("shored_area", 0.0),
            )
            self.add_project(project)


def _percentile(data: list[float], pct: int) -> float:
    """Calculate percentile from a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

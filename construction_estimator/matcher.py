"""
Similar project matching engine.

Finds the most similar historical projects to a target project based on
weighted similarity across multiple dimensions:
- GBA (Gross Building Area)
- Unit count
- Unit mix (ratio of 1BR/2BR/Studio)
- Construction type (wood, concrete, mixed)
- Number of floors
"""

import math
from construction_estimator.models import Project


# Weights for each similarity dimension (must sum to 1.0)
DEFAULT_WEIGHTS = {
    "gba": 0.30,
    "units": 0.25,
    "unit_mix": 0.15,
    "construction_type": 0.15,
    "num_floors": 0.15,
}


class ProjectMatcher:
    """Finds similar historical projects based on project characteristics."""

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or DEFAULT_WEIGHTS

    def find_similar(
        self,
        projects: list[Project],
        target_gba: float,
        target_units: int,
        target_unit_mix: dict[str, int],
        target_construction_type: str = "wood",
        target_num_floors: int = 5,
        top_n: int = 5,
    ) -> list[tuple[Project, float]]:
        """Find the most similar projects to the target parameters.

        Args:
            projects: List of historical projects to search
            target_gba: Target gross building area (SF)
            target_units: Target number of units
            target_unit_mix: Target unit mix, e.g., {"1BR": 50, "2BR": 30}
            target_construction_type: "wood", "concrete", or "mixed"
            target_num_floors: Number of floors
            top_n: Number of results to return

        Returns:
            List of (Project, similarity_score) tuples, highest score first.
            Scores are 0.0-1.0 where 1.0 is identical.
        """
        scored = []
        for project in projects:
            score = self._compute_similarity(
                project,
                target_gba,
                target_units,
                target_unit_mix,
                target_construction_type,
                target_num_floors,
            )
            scored.append((project, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def _compute_similarity(
        self,
        project: Project,
        target_gba: float,
        target_units: int,
        target_unit_mix: dict[str, int],
        target_construction_type: str,
        target_num_floors: int,
    ) -> float:
        """Compute weighted similarity score between project and target."""
        scores = {}

        # GBA similarity (exponential decay based on % difference)
        if target_gba > 0 and project.gba > 0:
            gba_ratio = abs(project.gba - target_gba) / target_gba
            scores["gba"] = math.exp(-2 * gba_ratio)
        else:
            scores["gba"] = 0.0

        # Unit count similarity
        if target_units > 0 and project.total_units > 0:
            unit_ratio = abs(project.total_units - target_units) / target_units
            scores["units"] = math.exp(-2 * unit_ratio)
        else:
            scores["units"] = 0.0

        # Unit mix similarity (cosine similarity of mix vectors)
        scores["unit_mix"] = self._unit_mix_similarity(
            project.unit_mix, target_unit_mix
        )

        # Construction type similarity
        if project.construction_type == target_construction_type:
            scores["construction_type"] = 1.0
        elif "mixed" in (project.construction_type, target_construction_type):
            scores["construction_type"] = 0.5
        else:
            scores["construction_type"] = 0.0

        # Floor count similarity
        if target_num_floors > 0 and project.num_floors > 0:
            floor_diff = abs(project.num_floors - target_num_floors)
            scores["num_floors"] = max(0.0, 1.0 - floor_diff * 0.25)
        else:
            scores["num_floors"] = 0.0

        # Weighted sum
        total = sum(
            scores.get(dim, 0.0) * weight
            for dim, weight in self.weights.items()
        )
        return total

    def _unit_mix_similarity(
        self, mix_a: dict[str, int], mix_b: dict[str, int]
    ) -> float:
        """Cosine similarity between two unit mix vectors."""
        all_types = set(mix_a.keys()) | set(mix_b.keys())
        if not all_types:
            return 0.0

        total_a = sum(mix_a.values())
        total_b = sum(mix_b.values())

        if total_a == 0 or total_b == 0:
            return 0.0

        # Normalize to ratios
        vec_a = [mix_a.get(t, 0) / total_a for t in all_types]
        vec_b = [mix_b.get(t, 0) / total_b for t in all_types]

        # Cosine similarity
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot / (mag_a * mag_b)

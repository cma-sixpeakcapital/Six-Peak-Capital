"""
LV Construction Cost Estimator

Estimates construction project costs using historical bid data from
the LV Construction Cost Estimator spreadsheets stored in Box.

Usage:
    from construction_estimator import EstimatorEngine, HistoricalDatabase

    db = HistoricalDatabase()
    db.load_from_box()  # or db.load_from_files(["path1.xlsx", "path2.xlsx"])

    engine = EstimatorEngine(db)
    estimate = engine.estimate(
        gba=50000,
        units=80,
        unit_mix={"1BR": 50, "2BR": 30},
        construction_type="wood",
    )
    estimate.summary()
"""

from construction_estimator.models import (
    Project,
    CostLineItem,
    Division,
    Estimate,
    EstimateLineItem,
)
from construction_estimator.parser import EstimatorParser
from construction_estimator.database import HistoricalDatabase
from construction_estimator.matcher import ProjectMatcher
from construction_estimator.estimator import EstimatorEngine

__version__ = "0.1.0"

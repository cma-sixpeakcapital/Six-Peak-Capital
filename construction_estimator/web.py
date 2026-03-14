"""Flask web portal for the Construction Cost Estimator."""

import sys
from pathlib import Path

from flask import Flask, render_template, request

from construction_estimator.database import HistoricalDatabase
from construction_estimator.estimator import EstimatorEngine
from construction_estimator.main import parse_unit_mix

app = Flask(__name__)
app.jinja_env.globals.update(zip=zip)

DB_PATH = Path(__file__).parent / "historical_data.json"
db = HistoricalDatabase()
db.load(str(DB_PATH))
engine = EstimatorEngine(db)


@app.template_filter("currency")
def currency_filter(value):
    try:
        return f"${value:,.0f}"
    except (TypeError, ValueError):
        return "$0"


@app.template_filter("currency2")
def currency2_filter(value):
    try:
        return f"${value:,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


@app.template_filter("pct")
def pct_filter(value):
    try:
        return f"{value:.0%}"
    except (TypeError, ValueError):
        return "0%"


@app.route("/")
def index():
    return render_template(
        "index.html",
        projects=db.projects,
        estimate=None,
        db_cost_codes=len(db.get_all_cost_codes()),
    )


@app.route("/estimate", methods=["POST"])
def estimate():
    try:
        gba = float(request.form.get("gba", "0").replace(",", ""))
        units = int(request.form.get("units", "0").replace(",", ""))
        mix_str = request.form.get("unit_mix", "")
        unit_mix = parse_unit_mix(mix_str) if mix_str else {"1BR": units}
        construction_type = request.form.get("construction_type", "wood")
        num_floors = int(request.form.get("num_floors", "5"))
        gc_fee = float(request.form.get("gc_fee", "6.0"))
        bonding = float(request.form.get("bonding", "1.0"))
        admin = float(request.form.get("admin", "2.0"))

        cost_codes = len(db.get_all_cost_codes())

        if gba <= 0 or units <= 0:
            return render_template(
                "index.html",
                projects=db.projects,
                estimate=None,
                error="GBA and Units must be greater than zero.",
                form=request.form,
                db_cost_codes=cost_codes,
            )

        result = engine.estimate(
            gba=gba,
            units=units,
            unit_mix=unit_mix,
            construction_type=construction_type,
            num_floors=num_floors,
            gc_fee_pct=gc_fee,
            bonding_pct=bonding,
            admin_pct=admin,
        )

        return render_template(
            "index.html",
            projects=db.projects,
            estimate=result,
            form=request.form,
            db_cost_codes=cost_codes,
        )

    except (ValueError, TypeError) as e:
        return render_template(
            "index.html",
            projects=db.projects,
            estimate=None,
            error=f"Invalid input: {e}",
            form=request.form,
            db_cost_codes=len(db.get_all_cost_codes()),
        )


if __name__ == "__main__":
    print(f"Loaded {db.project_count} historical projects from {DB_PATH}")
    app.run(debug=True, port=5000)

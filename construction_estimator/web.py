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
        gba_concrete = float(request.form.get("gba_concrete", "0").replace(",", ""))
        gba_wood = float(request.form.get("gba_wood", "0").replace(",", ""))
        podium_levels = int(request.form.get("podium_levels", "1"))
        wood_levels = int(request.form.get("wood_levels", "4"))
        lot_size = float(request.form.get("lot_size", "0").replace(",", ""))
        on_site_parking = bool(request.form.get("on_site_parking"))
        underground_parking = bool(request.form.get("underground_parking"))
        shored_area = float(request.form.get("shored_area", "0").replace(",", ""))
        parking_spaces = int(request.form.get("parking_spaces", "0"))

        units_0br = int(request.form.get("units_0br", "0"))
        units_1br = int(request.form.get("units_1br", "0"))
        units_2br = int(request.form.get("units_2br", "0"))
        units_3br = int(request.form.get("units_3br", "0"))

        unit_mix = {
            "0BR": units_0br,
            "1BR": units_1br,
            "2BR": units_2br,
            "3BR": units_3br,
        }
        units = units_0br + units_1br + units_2br + units_3br

        elevator_count = int(request.form.get("elevator_count", "2"))
        elevator_stops = int(request.form.get("elevator_stops", "7"))

        gc_fee = float(request.form.get("gc_fee", "6.0"))
        bonding = float(request.form.get("bonding", "1.0"))
        admin = float(request.form.get("admin", "2.0"))

        cost_codes = len(db.get_all_cost_codes())

        total_gba = gba_concrete + gba_wood

        if total_gba <= 0 or units <= 0:
            return render_template(
                "index.html",
                projects=db.projects,
                estimate=None,
                error="Total GBA and total units must be greater than zero.",
                form=request.form,
                db_cost_codes=cost_codes,
            )

        result = engine.estimate(
            gba_concrete=gba_concrete,
            gba_wood=gba_wood,
            units=units,
            unit_mix=unit_mix,
            num_floors=podium_levels + wood_levels,
            gc_fee_pct=gc_fee,
            bonding_pct=bonding,
            admin_pct=admin,
            podium_levels=podium_levels,
            wood_levels=wood_levels,
            elevator_count=elevator_count,
            elevator_stops=elevator_stops,
            lot_size=lot_size,
            shored_area=shored_area,
        )

        return render_template(
            "index.html",
            projects=db.projects,
            estimate=result,
            form=request.form,
            db_cost_codes=cost_codes,
            gba_concrete=gba_concrete,
            gba_wood=gba_wood,
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

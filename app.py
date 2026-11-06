# -*- coding: utf-8 -*-
import os
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

from planner import (
    SHIFT_LABELS,
    default_scenario,
    generate_schedule,
    validate_scenario,
)
from verifier import verify_schedule

app = Flask(__name__)
_schedules: dict[str, dict] = {}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/scenario")
def scenario_defaults():
    scenario = default_scenario()
    scenario["shift_labels"] = SHIFT_LABELS
    return jsonify(scenario)


@app.post("/api/schedules")
def create_schedule():
    if not request.is_json:
        return jsonify({"error": "Envía el escenario como JSON."}), 415
    scenario, errors = validate_scenario(request.get_json(silent=True))
    if errors:
        return jsonify({"error": "El escenario contiene datos inválidos.", "details": errors}), 400

    result = generate_schedule(scenario)
    if result["status"] == "infeasible":
        return jsonify(
            {
                "error": "No existe un cuadrante que cumpla todas las restricciones obligatorias.",
                "status": "infeasible",
            }
        ), 409
    if result["status"] == "unknown":
        return jsonify(
            {
                "error": "El solver no pudo encontrar una solución dentro del tiempo disponible.",
                "status": "unknown",
            }
        ), 503

    verification = verify_schedule(scenario, result["assignments"])
    if not verification["valid"]:
        app.logger.error("El verificador rechazó una solución del solver: %s", verification)
        return jsonify(
            {
                "error": "La verificación independiente ha rechazado el cuadrante.",
                "verification": verification,
            }
        ), 500

    schedule_id = str(uuid4())
    schedule = {
        "id": schedule_id,
        "status": result["status"],
        "start_date": scenario["start_date"].isoformat(),
        "weeks": scenario["weeks"],
        "coverage": scenario["coverage"],
        "assignments": result["assignments"],
        "verification": verification,
        "objective": result["objective"],
        "approved": False,
    }
    _schedules[schedule_id] = {"schedule": schedule, "scenario": scenario}
    return jsonify(schedule), 201


@app.post("/api/schedules/<schedule_id>/approve")
def approve_schedule(schedule_id: str):
    stored = _schedules.get(schedule_id)
    if stored is None:
        return jsonify({"error": "El cuadrante no existe o ya no está en memoria."}), 404
    verification = verify_schedule(stored["scenario"], stored["schedule"]["assignments"])
    if not verification["valid"]:
        return jsonify(
            {
                "error": "No se puede aprobar un cuadrante que no supera la verificación.",
                "verification": verification,
            }
        ), 409
    stored["schedule"]["approved"] = True
    return jsonify(stored["schedule"])


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")), debug=False)

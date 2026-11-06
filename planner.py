"""Generación de cuadrantes con restricciones usando OR-Tools CP-SAT."""

from datetime import date, datetime, time, timedelta

from ortools.sat.python import cp_model

SHIFTS = ("morning", "afternoon", "night")
SHIFT_LABELS = {
    "morning": "Mañana",
    "afternoon": "Tarde",
    "night": "Noche",
}
SHIFT_START_HOURS = {"morning": 6, "afternoon": 14, "night": 22}
SHIFT_DURATION_HOURS = 8
MINIMUM_REST_HOURS = 12
WEEKS = 4
DEFAULT_COVERAGE = {"morning": 2, "afternoon": 2, "night": 1}
MAX_EMPLOYEES = 30


def default_scenario(start_date: date | None = None) -> dict:
    """Return the example scenario described in the project document."""
    if start_date is None:
        today = date.today()
        start_date = today + timedelta(days=(-today.weekday()) % 7)
    return {
        "start_date": start_date.isoformat(),
        "weeks": WEEKS,
        "coverage": DEFAULT_COVERAGE.copy(),
        "employees": [
            {
                "id": f"employee-{number}",
                "name": f"Empleado {number}",
                "max_shifts_per_week": 5,
                "unavailable_dates": [],
                "eligible_shifts": list(SHIFTS),
                "preferred_shifts": [],
                "preferred_assignments": [],
            }
            for number in range(1, 9)
        ],
        "fixed_assignments": [],
    }


def validate_scenario(data: object) -> tuple[dict | None, list[str]]:
    """Validate and normalize structured input before it reaches the solver."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["El cuerpo de la petición debe ser un objeto JSON."]

    requested_weeks = data.get("weeks", WEEKS)
    if requested_weeks != WEEKS:
        errors.append(f"Este prototipo admite exactamente {WEEKS} semanas.")

    start_date = _parse_date(data.get("start_date"))
    if start_date is None:
        errors.append("start_date debe ser una fecha válida con formato AAAA-MM-DD.")
    elif start_date.weekday() != 0:
        errors.append("start_date debe ser lunes para alinear las cuatro semanas.")

    employees_data = data.get("employees")
    if not isinstance(employees_data, list) or not 2 <= len(employees_data) <= MAX_EMPLOYEES:
        errors.append(f"employees debe incluir entre 2 y {MAX_EMPLOYEES} personas.")
        employees_data = []

    employee_ids: set[str] = set()
    employees: list[dict] = []
    horizon_start = start_date
    horizon_end = start_date + timedelta(days=WEEKS * 7) if start_date else None
    for index, employee in enumerate(employees_data):
        prefix = f"employees[{index}]"
        if not isinstance(employee, dict):
            errors.append(f"{prefix} debe ser un objeto.")
            continue

        employee_id = employee.get("id")
        name = employee.get("name")
        if not isinstance(employee_id, str) or not employee_id.strip():
            errors.append(f"{prefix}.id es obligatorio.")
            continue
        employee_id = employee_id.strip()
        if employee_id in employee_ids:
            errors.append(f"El identificador {employee_id} está repetido.")
        employee_ids.add(employee_id)
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}.name es obligatorio.")
            name = employee_id

        max_shifts = employee.get("max_shifts_per_week", 5)
        if isinstance(max_shifts, bool) or not isinstance(max_shifts, int) or not 0 <= max_shifts <= 5:
            errors.append(f"{prefix}.max_shifts_per_week debe ser un entero entre 0 y 5.")
            max_shifts = 5

        unavailable_dates = _parse_date_list(
            employee.get("unavailable_dates", []),
            f"{prefix}.unavailable_dates",
            errors,
        )
        for unavailable_date in unavailable_dates:
            if horizon_start and horizon_end and not horizon_start <= unavailable_date < horizon_end:
                errors.append(f"{prefix}: el día no disponible {unavailable_date} queda fuera del cuadrante.")

        preferred_shifts = employee.get("preferred_shifts", [])
        if not isinstance(preferred_shifts, list) or any(
            shift not in SHIFTS for shift in preferred_shifts
        ):
            errors.append(f"{prefix}.preferred_shifts solo admite morning, afternoon o night.")
            preferred_shifts = []

        eligible_shifts = employee.get("eligible_shifts", list(SHIFTS))
        if not isinstance(eligible_shifts, list) or any(
            shift not in SHIFTS for shift in eligible_shifts
        ):
            errors.append(f"{prefix}.eligible_shifts solo admite morning, afternoon o night.")
            eligible_shifts = list(SHIFTS)

        preferred_assignments = _parse_assignments(
            employee.get("preferred_assignments", []),
            f"{prefix}.preferred_assignments",
            errors,
            horizon_start,
            horizon_end,
            employee_id,
        )
        employees.append(
            {
                "id": employee_id,
                "name": name.strip() if isinstance(name, str) else employee_id,
                "max_shifts_per_week": max_shifts,
                "unavailable_dates": unavailable_dates,
                "preferred_shifts": list(dict.fromkeys(preferred_shifts)),
                "eligible_shifts": list(dict.fromkeys(eligible_shifts)),
                "preferred_assignments": preferred_assignments,
            }
        )

    coverage_data = data.get("coverage", DEFAULT_COVERAGE)
    coverage: dict[str, int] = {}
    if not isinstance(coverage_data, dict):
        errors.append("coverage debe ser un objeto con los mínimos por turno.")
        coverage_data = {}
    for shift in SHIFTS:
        count = coverage_data.get(shift)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append(f"coverage.{shift} debe ser un entero positivo.")
            continue
        if employees and count > len(employees):
            errors.append(f"coverage.{shift} no puede superar el número de empleados.")
        coverage[shift] = count
    if set(coverage_data) - set(SHIFTS):
        errors.append("coverage contiene turnos desconocidos.")

    fixed_assignments = _parse_assignments(
        data.get("fixed_assignments", []),
        "fixed_assignments",
        errors,
        horizon_start,
        horizon_end,
        None,
    )
    for assignment in fixed_assignments:
        if assignment["employee_id"] not in employee_ids:
            errors.append(f"fixed_assignments referencia a {assignment['employee_id']} desconocido.")

    if errors:
        return None, errors
    return {
        "start_date": start_date,
        "weeks": WEEKS,
        "coverage": coverage,
        "employees": employees,
        "fixed_assignments": fixed_assignments,
    }, []


def generate_schedule(scenario: dict, _allow_overstaffing: bool = False) -> dict:
    """Find a minimum-coverage roster, then improve fairness and preferences."""
    start_date: date = scenario["start_date"]
    dates = [start_date + timedelta(days=offset) for offset in range(WEEKS * 7)]
    employees = scenario["employees"]
    model = cp_model.CpModel()
    assigned = {
        (employee["id"], day, shift): model.NewBoolVar(
            f"work_{employee['id']}_{day:%Y%m%d}_{shift}"
        )
        for employee in employees
        for day in dates
        for shift in SHIFTS
    }

    for day in dates:
        for shift in SHIFTS:
            staffed = sum(assigned[(employee["id"], day, shift)] for employee in employees)
            if _allow_overstaffing:
                model.Add(staffed >= scenario["coverage"][shift])
            else:
                model.Add(staffed == scenario["coverage"][shift])
        for employee in employees:
            model.Add(
                sum(assigned[(employee["id"], day, shift)] for shift in SHIFTS) <= 1
            )

    for employee in employees:
        employee_id = employee["id"]
        unavailable = set(employee["unavailable_dates"])
        for day in unavailable:
            for shift in SHIFTS:
                model.Add(assigned[(employee_id, day, shift)] == 0)
        eligible_shifts = set(employee["eligible_shifts"])
        for shift in SHIFTS:
            if shift not in eligible_shifts:
                for day in dates:
                    model.Add(assigned[(employee_id, day, shift)] == 0)

        for week in range(WEEKS):
            week_dates = dates[week * 7:(week + 1) * 7]
            model.Add(
                sum(
                    assigned[(employee_id, day, shift)]
                    for day in week_dates
                    for shift in SHIFTS
                )
                <= employee["max_shifts_per_week"]
            )

        for offset in range(len(dates) - 5):
            six_day_window = dates[offset:offset + 6]
            model.Add(
                sum(
                    assigned[(employee_id, day, shift)]
                    for day in six_day_window
                    for shift in SHIFTS
                )
                <= 5
            )

        for day_index in range(len(dates) - 1):
            day = dates[day_index]
            next_day = dates[day_index + 1]
            for first_shift in SHIFTS:
                for next_shift in SHIFTS:
                    if _rest_hours(day, first_shift, next_day, next_shift) < MINIMUM_REST_HOURS:
                        model.Add(
                            assigned[(employee_id, day, first_shift)]
                            + assigned[(employee_id, next_day, next_shift)]
                            <= 1
                        )

    for fixed in scenario["fixed_assignments"]:
        model.Add(
            assigned[(fixed["employee_id"], fixed["date"], fixed["shift"])] == 1
        )

    total_assignments = sum(assigned.values())
    solver = _new_solver()
    model.Minimize(total_assignments)
    first_status = solver.Solve(model)
    if first_status == cp_model.INFEASIBLE:
        if not _allow_overstaffing:
            return generate_schedule(scenario, _allow_overstaffing=True)
        return {"status": "infeasible", "assignments": []}
    if first_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if not _allow_overstaffing:
            return generate_schedule(scenario, _allow_overstaffing=True)
        return {"status": "unknown", "assignments": []}

    minimum_assignments = solver.Value(total_assignments)
    best_assignments = _read_assignments(dates, employees, assigned, solver)
    model.Add(total_assignments == minimum_assignments)

    workloads = [
        sum(
            assigned[(employee["id"], day, shift)]
            for day in dates
            for shift in SHIFTS
        )
        for employee in employees
    ]
    night_counts = [
        sum(assigned[(employee["id"], day, "night")] for day in dates)
        for employee in employees
    ]
    weekend_counts = [
        sum(
            assigned[(employee["id"], day, shift)]
            for day in dates
            if day.weekday() >= 5
            for shift in SHIFTS
        )
        for employee in employees
    ]
    workload_range = _range_expression(model, workloads, "workload")
    night_range = _range_expression(model, night_counts, "nights")
    weekend_range = _range_expression(model, weekend_counts, "weekends")

    preferred_variables = []
    for employee in employees:
        employee_id = employee["id"]
        for day in dates:
            for shift in employee["preferred_shifts"]:
                preferred_variables.append(assigned[(employee_id, day, shift)])
        for preferred in employee["preferred_assignments"]:
            preferred_variables.append(
                assigned[(employee_id, preferred["date"], preferred["shift"])]
            )

    preference_reward = sum(preferred_variables) if preferred_variables else 0
    model.Minimize(
        100 * workload_range
        + 50 * night_range
        + 50 * weekend_range
        - 5 * preference_reward
    )
    solver = _new_solver()
    second_status = solver.Solve(model)
    if second_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "feasible",
            "assignments": best_assignments,
            "objective": {
                "minimum_staffing_proven": first_status == cp_model.OPTIMAL,
                "fairness_optimal": False,
            },
        }

    return {
        "status": "optimal" if second_status == cp_model.OPTIMAL else "feasible",
        "assignments": _read_assignments(dates, employees, assigned, solver),
        "objective": {
            "minimum_staffing_proven": first_status == cp_model.OPTIMAL,
            "fairness_optimal": second_status == cp_model.OPTIMAL,
        },
    }


def _new_solver() -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    return solver


def _read_assignments(dates: list[date], employees: list[dict],
                      assigned: dict, solver: cp_model.CpSolver) -> list[dict]:
    rows = []
    for employee in employees:
        for day in dates:
            for shift in SHIFTS:
                if solver.Value(assigned[(employee["id"], day, shift)]):
                    rows.append(
                        {
                            "employee_id": employee["id"],
                            "employee_name": employee["name"],
                            "date": day.isoformat(),
                            "shift": shift,
                            "shift_label": SHIFT_LABELS[shift],
                        }
                    )
    return rows


def _range_expression(model: cp_model.CpModel, values: list, name: str):
    maximum = model.NewIntVar(0, WEEKS * 7 * 3, f"{name}_max")
    minimum = model.NewIntVar(0, WEEKS * 7 * 3, f"{name}_min")
    model.AddMaxEquality(maximum, values)
    model.AddMinEquality(minimum, values)
    return maximum - minimum


def _rest_hours(first_day: date, first_shift: str, second_day: date, second_shift: str) -> float:
    first_start = datetime.combine(
        first_day,
        time(hour=SHIFT_START_HOURS[first_shift]),
    )
    first_end = first_start + timedelta(hours=SHIFT_DURATION_HOURS)
    second_start = datetime.combine(
        second_day,
        time(hour=SHIFT_START_HOURS[second_shift]),
    )
    return (second_start - first_end).total_seconds() / 3600


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _parse_date_list(value: object, field: str, errors: list[str]) -> list[date]:
    if not isinstance(value, list):
        errors.append(f"{field} debe ser una lista de fechas.")
        return []
    parsed_dates = []
    for item in value:
        parsed = _parse_date(item)
        if parsed is None:
            errors.append(f"{field} contiene una fecha inválida: {item!r}.")
        elif parsed not in parsed_dates:
            parsed_dates.append(parsed)
    return parsed_dates


def _parse_assignments(
    value: object,
    field: str,
    errors: list[str],
    horizon_start: date | None,
    horizon_end: date | None,
    default_employee_id: str | None,
) -> list[dict]:
    if not isinstance(value, list):
        errors.append(f"{field} debe ser una lista.")
        return []
    parsed_assignments = []
    seen: set[tuple[str | None, date, str]] = set()
    for index, item in enumerate(value):
        prefix = f"{field}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} debe ser un objeto.")
            continue
        employee_id = item.get("employee_id", default_employee_id)
        day = _parse_date(item.get("date"))
        shift = item.get("shift")
        if not isinstance(employee_id, str) or not employee_id:
            errors.append(f"{prefix}.employee_id es obligatorio.")
        if day is None:
            errors.append(f"{prefix}.date debe tener formato AAAA-MM-DD.")
        elif horizon_start and horizon_end and not horizon_start <= day < horizon_end:
            errors.append(f"{prefix}.date queda fuera del cuadrante.")
        if shift not in SHIFTS:
            errors.append(f"{prefix}.shift solo admite morning, afternoon o night.")
        if isinstance(employee_id, str) and day is not None and shift in SHIFTS:
            key = (employee_id, day, shift)
            if key in seen:
                errors.append(f"{field} contiene una asignación repetida.")
            seen.add(key)
            parsed_assignments.append(
                {"employee_id": employee_id, "date": day, "shift": shift}
            )
    return parsed_assignments

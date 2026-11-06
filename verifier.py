"""Independent rule-by-rule verification for generated schedules."""

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta


SHIFT_START_HOURS = {"morning": 6, "afternoon": 14, "night": 22}
SHIFT_DURATION_HOURS = 8
MINIMUM_REST_HOURS = 12


def verify_schedule(scenario: dict, assignments: list[dict]) -> dict:
    """Check hard constraints without relying on the solver model."""
    violations: list[dict] = []
    employees = {employee["id"]: employee for employee in scenario["employees"]}
    start_date: date = scenario["start_date"]
    horizon_end = start_date + timedelta(days=28)
    dates = [start_date + timedelta(days=offset) for offset in range(28)]
    daily_coverage: Counter[tuple[date, str]] = Counter()
    employee_days: dict[str, set[date]] = defaultdict(set)
    employee_shifts: dict[str, list[tuple[date, str]]] = defaultdict(list)
    employee_weekly: Counter[tuple[str, int]] = Counter()
    seen_employee_days: set[tuple[str, date]] = set()
    seen_assignments: set[tuple[str, date, str]] = set()

    def report(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    for index, assignment in enumerate(assignments):
        try:
            employee_id = assignment["employee_id"]
            day = date.fromisoformat(assignment["date"])
            shift = assignment["shift"]
        except (KeyError, TypeError, ValueError):
            report("invalid_assignment", f"La asignación {index + 1} tiene datos inválidos.")
            continue
        if employee_id not in employees:
            report("unknown_employee", f"La asignación {index + 1} referencia a una persona desconocida.")
            continue
        if shift not in SHIFT_START_HOURS:
            report("unknown_shift", f"La asignación {index + 1} contiene un turno desconocido.")
            continue
        if not start_date <= day < horizon_end:
            report("outside_period", f"La asignación de {employee_id} del {day} queda fuera del periodo.")
            continue

        assignment_key = (employee_id, day, shift)
        if assignment_key in seen_assignments:
            report("duplicate_assignment", f"{employee_id} tiene una asignación duplicada el {day}.")
            continue
        seen_assignments.add(assignment_key)

        employee_day = (employee_id, day)
        if employee_day in seen_employee_days:
            report("multiple_shifts_per_day", f"{employee_id} tiene más de un turno el {day}.")
        seen_employee_days.add(employee_day)

        employee = employees[employee_id]
        if day in employee["unavailable_dates"]:
            report("unavailable_day", f"{employee_id} trabaja en un día no disponible ({day}).")
        if shift not in employee["eligible_shifts"]:
            report("unqualified_shift", f"{employee_id} no está habilitado para el turno {shift}.")

        daily_coverage[(day, shift)] += 1
        employee_days[employee_id].add(day)
        employee_shifts[employee_id].append((day, shift))
        employee_weekly[(employee_id, (day - start_date).days // 7)] += 1

    for day in dates:
        for shift, minimum in scenario["coverage"].items():
            actual = daily_coverage[(day, shift)]
            if actual < minimum:
                report(
                    "insufficient_coverage",
                    f"{day} ({shift}): cobertura {actual}; mínimo requerido {minimum}.",
                )

    for employee_id, employee in employees.items():
        for week in range(4):
            actual = employee_weekly[(employee_id, week)]
            if actual > employee["max_shifts_per_week"]:
                report(
                    "weekly_limit",
                    f"{employee_id} supera su máximo semanal en la semana {week + 1}.",
                )

        worked_days = employee_days[employee_id]
        for offset in range(23):
            window = dates[offset:offset + 6]
            if sum(day in worked_days for day in window) > 5:
                report(
                    "consecutive_days",
                    f"{employee_id} trabaja más de 5 días consecutivos desde {window[0]}.",
                )

        shifts = sorted(employee_shifts[employee_id])
        for (first_day, first_shift), (second_day, second_shift) in zip(shifts, shifts[1:]):
            first_start = datetime.combine(
                first_day,
                time(hour=SHIFT_START_HOURS[first_shift]),
            )
            first_end = first_start + timedelta(hours=SHIFT_DURATION_HOURS)
            second_start = datetime.combine(
                second_day,
                time(hour=SHIFT_START_HOURS[second_shift]),
            )
            rest_hours = (second_start - first_end).total_seconds() / 3600
            if rest_hours < MINIMUM_REST_HOURS:
                report(
                    "minimum_rest",
                    f"{employee_id} solo descansa {rest_hours:g} horas entre "
                    f"{first_day} ({first_shift}) y {second_day} ({second_shift}).",
                )

    actual_assignments = seen_assignments
    for fixed in scenario["fixed_assignments"]:
        key = (fixed["employee_id"], fixed["date"], fixed["shift"])
        if key not in actual_assignments:
            report("missing_fixed_assignment", f"No se ha respetado el turno fijado {key}.")
    return {"valid": not violations, "violations": violations}

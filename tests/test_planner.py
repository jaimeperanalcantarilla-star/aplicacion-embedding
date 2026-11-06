import unittest
from datetime import date, timedelta

from planner import default_scenario, generate_schedule, validate_scenario
from verifier import verify_schedule


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.raw_scenario = default_scenario(date(2026, 11, 2))
        self.scenario, errors = validate_scenario(self.raw_scenario)
        self.assertEqual(errors, [])

    def test_default_scenario_is_solved_and_independently_verified(self):
        result = generate_schedule(self.scenario)
        self.assertIn(result["status"], ("optimal", "feasible"))
        verification = verify_schedule(self.scenario, result["assignments"])
        self.assertTrue(verification["valid"], verification["violations"])
        self.assertEqual(len(result["assignments"]), 28 * (2 + 2 + 1))

    def test_rejects_non_monday_start(self):
        invalid = default_scenario(date(2026, 11, 3))
        scenario, errors = validate_scenario(invalid)
        self.assertIsNone(scenario)
        self.assertTrue(any("lunes" in error for error in errors))

    def test_rejects_unsupported_period_length(self):
        self.raw_scenario["weeks"] = 6
        scenario, errors = validate_scenario(self.raw_scenario)
        self.assertIsNone(scenario)
        self.assertTrue(any("exactamente 4 semanas" in error for error in errors))

    def test_rejects_unknown_shift_preference(self):
        self.raw_scenario["employees"][0]["preferred_shifts"] = ["midday"]
        scenario, errors = validate_scenario(self.raw_scenario)
        self.assertIsNone(scenario)
        self.assertTrue(any("preferred_shifts" in error for error in errors))

    def test_respects_fixed_shifts_and_qualifications(self):
        employee = self.raw_scenario["employees"][0]
        employee["eligible_shifts"] = ["morning"]
        self.raw_scenario["fixed_assignments"] = [
            {
                "employee_id": employee["id"],
                "date": "2026-11-02",
                "shift": "morning",
            }
        ]
        scenario, errors = validate_scenario(self.raw_scenario)
        self.assertEqual(errors, [])
        result = generate_schedule(scenario)
        self.assertIn(result["status"], ("optimal", "feasible"))
        verification = verify_schedule(scenario, result["assignments"])
        self.assertTrue(verification["valid"], verification["violations"])
        self.assertIn(
            {
                "employee_id": employee["id"],
                "employee_name": employee["name"],
                "date": "2026-11-02",
                "shift": "morning",
                "shift_label": "Mañana",
            },
            result["assignments"],
        )

    def test_reports_impossible_coverage(self):
        for employee in self.raw_scenario["employees"]:
            employee["unavailable_dates"] = [
                (date(2026, 11, 2) + timedelta(days=offset)).isoformat()
                for offset in range(28)
            ]
        scenario, errors = validate_scenario(self.raw_scenario)
        self.assertEqual(errors, [])
        result = generate_schedule(scenario)
        self.assertEqual(result["status"], "infeasible")

    def test_verifier_detects_missing_coverage(self):
        verification = verify_schedule(self.scenario, [])
        self.assertFalse(verification["valid"])
        self.assertTrue(
            any(violation["code"] == "insufficient_coverage"
                for violation in verification["violations"])
        )

    def test_verifier_detects_insufficient_rest(self):
        employee_id = self.scenario["employees"][0]["id"]
        assignments = [
            {"employee_id": employee_id, "date": "2026-11-02", "shift": "night"},
            {"employee_id": employee_id, "date": "2026-11-03", "shift": "morning"},
        ]
        verification = verify_schedule(self.scenario, assignments)
        self.assertTrue(
            any(violation["code"] == "minimum_rest"
                for violation in verification["violations"])
        )


class AppApiTests(unittest.TestCase):
    def test_schedule_must_be_reviewed_and_approved(self):
        import app

        app.app.config["TESTING"] = True
        app._schedules.clear()
        client = app.app.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        scenario = client.get("/api/scenario").get_json()
        response = client.post("/api/schedules", json=scenario)
        self.assertEqual(response.status_code, 201, response.get_json())
        schedule = response.get_json()
        self.assertFalse(schedule["approved"])
        self.assertTrue(schedule["verification"]["valid"])

        approved = client.post(f"/api/schedules/{schedule['id']}/approve")
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(approved.get_json()["approved"])


if __name__ == "__main__":
    unittest.main()

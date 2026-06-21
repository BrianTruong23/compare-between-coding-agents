import io
import json
import tempfile
import unittest
from pathlib import Path

from app import create_app, init_db


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.db")
        self.export_path = str(Path(self.tmpdir.name) / "export.json")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.db_path,
                "EXPORT_PATH": self.export_path,
                "WTF_CSRF_ENABLED": False,
            }
        )
        init_db(self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_dashboard_loads_seeded_data(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Coding Agent Evaluation Dashboard", response.data)
        self.assertIn(b"Plan mode first -&gt; complete the task", response.data)
        self.assertIn(b"Codex", response.data)

    def test_create_records_and_filter(self):
        self.client.post("/projects", data={"name": "New Project", "description": "Test"})
        response = self.client.get("/")
        self.assertIn(b"New Project", response.data)

        self.client.post(
            "/methods",
            data={"name": "Strict checklist", "steps": "Plan, implement, verify."},
        )
        response = self.client.get("/?agent_name=Codex&status=satisfied")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Satisfied", response.data)

    def test_create_task_method_and_evaluation_updates_dashboard(self):
        self.client.post(
            "/methods",
            data={"name": "Strict checklist", "steps": "Plan, implement, verify."},
        )
        self.client.post(
            "/tasks",
            data={
                "project_id": "1",
                "title": "Add import screen",
                "original_request": "Add JSON restore UI.",
                "expected_outcome": "Validated imports with clear errors.",
            },
        )
        self.client.post(
            "/evaluations",
            data={
                "task_id": "2",
                "agent_name": "Cursor",
                "method_id": "2",
                "satisfied": "0",
                "confidence_score": "42",
                "issue_category": "Regression",
                "notes": "Import failed on required fields.",
                "repo_link": "",
                "result_link": "",
            },
        )

        response = self.client.get("/?status=failed")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Add import screen", response.data)
        self.assertIn(b"Regression", response.data)
        self.assertIn(b"42", response.data)

    def test_export_and_import_round_trip(self):
        export_response = self.client.post("/export")
        self.assertEqual(export_response.status_code, 200)
        export_response.close()
        payload = json.loads(Path(self.export_path).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["evaluations"]), 4)

        fresh_db = str(Path(self.tmpdir.name) / "fresh.db")
        fresh_app = create_app(
            {
                "TESTING": True,
                "DATABASE": fresh_db,
                "EXPORT_PATH": self.export_path,
            }
        )
        init_db(fresh_db)
        fresh_client = fresh_app.test_client()
        response = fresh_client.post(
            "/import",
            data={"json_file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "backup.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Import complete", response.data)
        self.assertIn(b"Antigravity", response.data)

    def test_import_validation_error(self):
        response = self.client.post(
            "/import",
            data={"json_file": (io.BytesIO(b'{"projects": []}'), "bad.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Import failed", response.data)


if __name__ == "__main__":
    unittest.main()

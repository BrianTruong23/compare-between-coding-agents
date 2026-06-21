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
            }
        )
        init_db(self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_dashboard_loads_seeded_data(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Coding Agent Task Tracker", response.data)
        self.assertIn(b"Plan mode first -&gt; complete the task", response.data)
        self.assertIn(b"POST /api/tasks", response.data)

    def test_manual_task_record_create_and_filter(self):
        self.client.post(
            "/tasks",
            data={
                "task_name": "Add API endpoint",
                "agent_name": "Codex",
                "repo_link": "https://github.com/example/repo",
                "satisfied": "1",
                "method_id": "1",
            },
        )

        response = self.client.get("/?agent_name=Codex&status=satisfied")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Add API endpoint", response.data)
        self.assertIn(b"Open repo", response.data)

    def test_agent_api_creates_task_record(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "task_name": "Refactor dashboard",
                "agent_name": "Cursor",
                "github_repo_link": "https://github.com/example/refactor",
                "satisfied": False,
                "instruction_method": "Plan mode first -> complete the task",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["task_name"], "Refactor dashboard")

        dashboard = self.client.get("/?status=failed")
        self.assertIn(b"Refactor dashboard", dashboard.data)
        self.assertIn(b"Not satisfied", dashboard.data)

    def test_agent_api_can_create_instruction_method(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "task_name": "Try alternate prompt",
                "agent_name": "Antigravity",
                "satisfied": "yes",
                "instruction_method": "No plan, direct implementation",
            },
        )
        self.assertEqual(response.status_code, 201)

        dashboard = self.client.get("/")
        self.assertIn(b"No plan, direct implementation", dashboard.data)

    def test_export_and_import_round_trip(self):
        export_response = self.client.post("/export")
        self.assertEqual(export_response.status_code, 200)
        export_response.close()
        payload = json.loads(Path(self.export_path).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["task_records"]), 4)

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
            data={"json_file": (io.BytesIO(b'{"task_records": []}'), "bad.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Import failed", response.data)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, send_file, url_for


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "evaluations.db"
DEFAULT_EXPORT_PATH = DATA_DIR / "export.json"
AGENTS = ["Codex", "Claude Code", "Cursor", "Antigravity"]
DEFAULT_METHOD = "Plan mode first -> complete the task"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=str(DEFAULT_DB_PATH),
        EXPORT_PATH=str(DEFAULT_EXPORT_PATH),
        SECRET_KEY="local-dev-dashboard",
    )
    if test_config:
        app.config.update(test_config)

    DATA_DIR.mkdir(exist_ok=True)

    @app.before_request
    def ensure_database():
        init_db(app.config["DATABASE"])

    @app.teardown_appcontext
    def close_connection(_exception):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.route("/")
    def dashboard():
        filters = {
            "project_id": request.args.get("project_id", ""),
            "agent_name": request.args.get("agent_name", ""),
            "status": request.args.get("status", ""),
            "method_id": request.args.get("method_id", ""),
        }
        data = dashboard_data(filters)
        return render_template("dashboard.html", agents=AGENTS, filters=filters, **data)

    @app.route("/projects", methods=["POST"])
    def save_project():
        project_id = request.form.get("id")
        name = require_form("name")
        description = request.form.get("description", "").strip()
        if project_id:
            query_db(
                "UPDATE projects SET name = ?, description = ? WHERE id = ?",
                (name, description, project_id),
                commit=True,
            )
            flash("Project updated.")
        else:
            query_db(
                "INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
                (name, description, now()),
                commit=True,
            )
            flash("Project created.")
        return redirect(url_for("dashboard"))

    @app.route("/tasks", methods=["POST"])
    def save_task():
        task_id = request.form.get("id")
        values = (
            require_form("project_id"),
            require_form("title"),
            request.form.get("original_request", "").strip(),
            request.form.get("expected_outcome", "").strip(),
        )
        if task_id:
            query_db(
                """
                UPDATE tasks
                SET project_id = ?, title = ?, original_request = ?, expected_outcome = ?
                WHERE id = ?
                """,
                values + (task_id,),
                commit=True,
            )
            flash("Task updated.")
        else:
            query_db(
                """
                INSERT INTO tasks
                    (project_id, title, original_request, expected_outcome, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                values + (now(),),
                commit=True,
            )
            flash("Task created.")
        return redirect(url_for("dashboard"))

    @app.route("/methods", methods=["POST"])
    def save_method():
        method_id = request.form.get("id")
        name = require_form("name")
        steps = request.form.get("steps", "").strip()
        if method_id:
            query_db(
                "UPDATE instruction_methods SET name = ?, steps = ? WHERE id = ?",
                (name, steps, method_id),
                commit=True,
            )
            flash("Instruction method updated.")
        else:
            query_db(
                "INSERT INTO instruction_methods (name, steps, created_at) VALUES (?, ?, ?)",
                (name, steps, now()),
                commit=True,
            )
            flash("Instruction method created.")
        return redirect(url_for("dashboard"))

    @app.route("/evaluations", methods=["POST"])
    def save_evaluation():
        evaluation_id = request.form.get("id")
        values = (
            require_form("task_id"),
            require_form("agent_name"),
            require_form("method_id"),
            1 if request.form.get("satisfied") == "1" else 0,
            parse_int(request.form.get("confidence_score"), 0, 100),
            request.form.get("issue_category", "").strip(),
            request.form.get("notes", "").strip(),
            request.form.get("repo_link", "").strip(),
            request.form.get("result_link", "").strip(),
        )
        if evaluation_id:
            query_db(
                """
                UPDATE evaluations
                SET task_id = ?, agent_name = ?, method_id = ?, satisfied = ?,
                    confidence_score = ?, issue_category = ?, notes = ?,
                    repo_link = ?, result_link = ?
                WHERE id = ?
                """,
                values + (evaluation_id,),
                commit=True,
            )
            flash("Evaluation updated.")
        else:
            query_db(
                """
                INSERT INTO evaluations
                    (task_id, agent_name, method_id, satisfied, confidence_score,
                     issue_category, notes, repo_link, result_link, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values + (now(),),
                commit=True,
            )
            flash("Evaluation created.")
        return redirect(url_for("dashboard"))

    @app.route("/export", methods=["POST"])
    def export_json():
        export_path = Path(app.config["EXPORT_PATH"])
        export_path.parent.mkdir(exist_ok=True)
        payload = export_data()
        export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        flash(f"Exported {sum(len(payload[key]) for key in payload)} records to {export_path}.")
        return send_file(export_path, as_attachment=True, download_name="coding-agent-evaluations.json")

    @app.route("/import", methods=["POST"])
    def import_json():
        uploaded = request.files.get("json_file")
        if not uploaded or uploaded.filename == "":
            flash("Choose a JSON file to import.", "error")
            return redirect(url_for("dashboard"))
        try:
            payload = json.loads(uploaded.read().decode("utf-8"))
            import_data(payload)
        except (json.JSONDecodeError, ValueError, KeyError, sqlite3.Error) as exc:
            flash(f"Import failed: {exc}", "error")
            return redirect(url_for("dashboard"))
        flash("Import complete.")
        return redirect(url_for("dashboard"))

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app_database())
        g.db.row_factory = sqlite3.Row
    return g.db


def current_app_database():
    from flask import current_app

    return current_app.config["DATABASE"]


def query_db(sql, params=(), one=False, commit=False):
    db = get_db()
    cursor = db.execute(sql, params)
    if commit:
        db.commit()
    rows = cursor.fetchall()
    return (rows[0] if rows else None) if one else rows


def init_db(path):
    db_path = Path(path)
    db_path.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                original_request TEXT DEFAULT '',
                expected_outcome TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS instruction_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                steps TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                method_id INTEGER NOT NULL,
                satisfied INTEGER NOT NULL CHECK (satisfied IN (0, 1)),
                confidence_score INTEGER NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
                issue_category TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                repo_link TEXT DEFAULT '',
                result_link TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (method_id) REFERENCES instruction_methods(id)
            );
            """
        )
        seed_db(db)
        db.commit()
    finally:
        db.close()


def seed_db(db):
    count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if count:
        return
    created = now()
    db.execute(
        "INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
        (
            "Agent Comparison Dashboard",
            "Track whether coding agents satisfy real project requests after plan-first prompting.",
            created,
        ),
    )
    project_id = db.execute("SELECT id FROM projects WHERE name = ?", ("Agent Comparison Dashboard",)).fetchone()[0]
    db.execute(
        """
        INSERT INTO instruction_methods (name, steps, created_at)
        VALUES (?, ?, ?)
        """,
        (
            DEFAULT_METHOD,
            "1. Ask the agent for a concrete implementation plan.\n"
            "2. Review the plan for missing assumptions or risky shortcuts.\n"
            "3. Ask the agent to complete the task end to end.\n"
            "4. Manually mark whether the result satisfied the original need.",
            created,
        ),
    )
    method_id = db.execute("SELECT id FROM instruction_methods WHERE name = ?", (DEFAULT_METHOD,)).fetchone()[0]
    db.execute(
        """
        INSERT INTO tasks
            (project_id, title, original_request, expected_outcome, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            "Build Flask evaluation tracker",
            "Create a local dashboard for comparing coding agents across the same task.",
            "Dashboard shows project/task records, pass-fail evaluations, confidence, issues, and import/export.",
            created,
        ),
    )
    task_id = db.execute("SELECT id FROM tasks WHERE title = ?", ("Build Flask evaluation tracker",)).fetchone()[0]
    seed_evaluations = [
        ("Codex", 1, 92, "", "Completed the requested Flask dashboard with verification."),
        ("Claude Code", 1, 86, "", "Strong plan and implementation, minor UI polish follow-up."),
        ("Cursor", 0, 64, "Incomplete workflow", "Missed JSON restore behavior in first pass."),
        ("Antigravity", 0, 58, "Verification gap", "Dashboard worked, but tests were not run."),
    ]
    for agent, satisfied, confidence, issue, notes in seed_evaluations:
        db.execute(
            """
            INSERT INTO evaluations
                (task_id, agent_name, method_id, satisfied, confidence_score,
                 issue_category, notes, repo_link, result_link, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, agent, method_id, satisfied, confidence, issue, notes, "", "", created),
        )


def dashboard_data(filters):
    where = []
    params = []
    if filters["project_id"]:
        where.append("p.id = ?")
        params.append(filters["project_id"])
    if filters["agent_name"]:
        where.append("e.agent_name = ?")
        params.append(filters["agent_name"])
    if filters["status"] == "satisfied":
        where.append("e.satisfied = 1")
    elif filters["status"] == "failed":
        where.append("e.satisfied = 0")
    if filters["method_id"]:
        where.append("m.id = ?")
        params.append(filters["method_id"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    evaluations = query_db(
        f"""
        SELECT e.*, t.title AS task_title, p.name AS project_name, m.name AS method_name
        FROM evaluations e
        JOIN tasks t ON t.id = e.task_id
        JOIN projects p ON p.id = t.project_id
        JOIN instruction_methods m ON m.id = e.method_id
        {where_sql}
        ORDER BY e.created_at DESC, e.id DESC
        """,
        tuple(params),
    )
    tasks = query_db(
        """
        SELECT t.*, p.name AS project_name
        FROM tasks t JOIN projects p ON p.id = t.project_id
        ORDER BY t.created_at DESC, t.id DESC
        """
    )
    projects = query_db("SELECT * FROM projects ORDER BY name")
    methods = query_db("SELECT * FROM instruction_methods ORDER BY name")

    total_tasks = len(tasks)
    total_evaluations = len(evaluations)
    satisfied_count = sum(1 for row in evaluations if row["satisfied"])
    failed_count = total_evaluations - satisfied_count
    expected_total = total_tasks * len(AGENTS)
    pending_count = max(expected_total - count_all_evaluations_for_visible_tasks(filters), 0)
    satisfaction_rate = round((satisfied_count / total_evaluations) * 100) if total_evaluations else 0

    agent_stats = []
    for agent in AGENTS:
        rows = [row for row in evaluations if row["agent_name"] == agent]
        passed = sum(1 for row in rows if row["satisfied"])
        avg_confidence = round(sum(row["confidence_score"] for row in rows) / len(rows)) if rows else 0
        agent_stats.append(
            {
                "agent": agent,
                "total": len(rows),
                "passed": passed,
                "failed": len(rows) - passed,
                "rate": round((passed / len(rows)) * 100) if rows else 0,
                "avg_confidence": avg_confidence,
            }
        )

    issue_counts = {}
    for row in evaluations:
        if not row["satisfied"]:
            label = row["issue_category"] or "Uncategorized"
            issue_counts[label] = issue_counts.get(label, 0) + 1
    issues = [{"category": key, "count": value} for key, value in sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)]

    confidence_trend = [
        {
            "label": row["created_at"][:10],
            "agent": row["agent_name"],
            "confidence": row["confidence_score"],
        }
        for row in list(reversed(evaluations[-12:]))
    ]

    return {
        "projects": projects,
        "tasks": tasks,
        "methods": methods,
        "evaluations": evaluations,
        "agent_stats": agent_stats,
        "issues": issues,
        "confidence_trend": confidence_trend,
        "summary": {
            "total_tasks": total_tasks,
            "satisfaction_rate": satisfaction_rate,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "total_evaluations": total_evaluations,
        },
    }


def count_all_evaluations_for_visible_tasks(filters):
    where = []
    params = []
    if filters["project_id"]:
        where.append("t.project_id = ?")
        params.append(filters["project_id"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    row = query_db(
        f"SELECT COUNT(*) AS count FROM evaluations e JOIN tasks t ON t.id = e.task_id {where_sql}",
        tuple(params),
        one=True,
    )
    return row["count"] if row else 0


def export_data():
    tables = ["projects", "tasks", "instruction_methods", "evaluations"]
    return {table: [dict(row) for row in query_db(f"SELECT * FROM {table} ORDER BY id")] for table in tables}


def import_data(payload):
    required = {
        "projects": ["id", "name", "created_at"],
        "tasks": ["id", "project_id", "title", "created_at"],
        "instruction_methods": ["id", "name", "created_at"],
        "evaluations": ["id", "task_id", "agent_name", "method_id", "satisfied", "confidence_score", "created_at"],
    }
    for table, fields in required.items():
        if table not in payload or not isinstance(payload[table], list):
            raise ValueError(f"missing list: {table}")
        for index, row in enumerate(payload[table], start=1):
            missing = [field for field in fields if field not in row]
            if missing:
                raise ValueError(f"{table} row {index} missing {', '.join(missing)}")

    db = get_db()
    with db:
        db.execute("PRAGMA foreign_keys = OFF")
        for table in ["evaluations", "tasks", "instruction_methods", "projects"]:
            db.execute(f"DELETE FROM {table}")
        insert_rows(db, "projects", payload["projects"])
        insert_rows(db, "instruction_methods", payload["instruction_methods"])
        insert_rows(db, "tasks", payload["tasks"])
        insert_rows(db, "evaluations", payload["evaluations"])
        db.execute("PRAGMA foreign_keys = ON")


def insert_rows(db, table, rows):
    if not rows:
        return
    allowed_fields = {
        "projects": ["id", "name", "description", "created_at"],
        "tasks": ["id", "project_id", "title", "original_request", "expected_outcome", "created_at"],
        "instruction_methods": ["id", "name", "steps", "created_at"],
        "evaluations": [
            "id",
            "task_id",
            "agent_name",
            "method_id",
            "satisfied",
            "confidence_score",
            "issue_category",
            "notes",
            "repo_link",
            "result_link",
            "created_at",
        ],
    }[table]
    for row in rows:
        fields = [field for field in allowed_fields if field in row]
        placeholders = ", ".join(["?"] * len(fields))
        db.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})",
            tuple(row.get(field) for field in fields),
        )


def require_form(name):
    value = request.form.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def parse_int(value, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=True, port=port)

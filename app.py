import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_file, url_for


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
            "agent_name": request.args.get("agent_name", ""),
            "status": request.args.get("status", ""),
            "method_id": request.args.get("method_id", ""),
        }
        data = dashboard_data(filters)
        return render_template("dashboard.html", agents=AGENTS, filters=filters, **data)

    @app.route("/tasks", methods=["POST"])
    def save_task():
        task_id = request.form.get("id")
        payload = {
            "task_name": require_form("task_name"),
            "agent_name": require_form("agent_name"),
            "repo_link": request.form.get("repo_link", "").strip(),
            "satisfied": parse_satisfied(request.form.get("satisfied")),
            "method_id": require_form("method_id"),
        }
        if task_id:
            update_task_record(task_id, payload)
            flash("Task record updated.")
        else:
            create_task_record(payload)
            flash("Task record added.")
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
            flash("Instruction method added.")
        return redirect(url_for("dashboard"))

    @app.route("/api/tasks", methods=["POST"])
    def api_add_task():
        payload = request.get_json(silent=True) or {}
        try:
            method_id = resolve_method(payload.get("instruction_method") or payload.get("method_name") or DEFAULT_METHOD)
            record = create_task_record(
                {
                    "task_name": clean_required(payload.get("task_name"), "task_name"),
                    "agent_name": clean_required(payload.get("agent_name"), "agent_name"),
                    "repo_link": (payload.get("repo_link") or payload.get("github_repo_link") or "").strip(),
                    "satisfied": parse_satisfied(payload.get("satisfied")),
                    "method_id": method_id,
                }
            )
        except (ValueError, sqlite3.Error) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "task": dict(record)}), 201

    @app.route("/export", methods=["POST"])
    def export_json():
        export_path = Path(app.config["EXPORT_PATH"])
        export_path.parent.mkdir(exist_ok=True)
        payload = export_data()
        export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        flash(f"Exported {sum(len(payload[key]) for key in payload)} records to {export_path}.")
        return send_file(export_path, as_attachment=True, download_name="coding-agent-tasks.json")

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
            CREATE TABLE IF NOT EXISTS instruction_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                steps TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                repo_link TEXT DEFAULT '',
                satisfied INTEGER NOT NULL CHECK (satisfied IN (0, 1)),
                method_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (method_id) REFERENCES instruction_methods(id)
            );
            """
        )
        seed_methods(db)
        migrate_old_evaluations(db)
        seed_records(db)
        db.commit()
    finally:
        db.close()


def seed_methods(db):
    existing = db.execute("SELECT id FROM instruction_methods WHERE name = ?", (DEFAULT_METHOD,)).fetchone()
    if existing:
        return
    db.execute(
        """
        INSERT INTO instruction_methods (name, steps, created_at)
        VALUES (?, ?, ?)
        """,
        (
            DEFAULT_METHOD,
            "1. Ask the agent for a concrete implementation plan.\n"
            "2. Review the plan.\n"
            "3. Ask the agent to complete the task.\n"
            "4. Record whether the result satisfied the need.",
            now(),
        ),
    )


def migrate_old_evaluations(db):
    old_tables = {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if "evaluations" not in old_tables or "tasks" not in old_tables:
        return
    has_records = db.execute("SELECT COUNT(*) FROM task_records").fetchone()[0]
    if has_records:
        return
    db.execute(
        """
        INSERT INTO task_records
            (task_name, agent_name, repo_link, satisfied, method_id, created_at, updated_at)
        SELECT
            t.title,
            e.agent_name,
            COALESCE(NULLIF(e.repo_link, ''), e.result_link, ''),
            e.satisfied,
            e.method_id,
            e.created_at,
            e.created_at
        FROM evaluations e
        JOIN tasks t ON t.id = e.task_id
        """
    )


def seed_records(db):
    count = db.execute("SELECT COUNT(*) FROM task_records").fetchone()[0]
    if count:
        return
    created = now()
    method_id = db.execute("SELECT id FROM instruction_methods WHERE name = ?", (DEFAULT_METHOD,)).fetchone()[0]
    examples = [
        ("Build Flask evaluation tracker", "Codex", "", 1),
        ("Build Flask evaluation tracker", "Claude Code", "", 1),
        ("Build Flask evaluation tracker", "Cursor", "", 0),
        ("Build Flask evaluation tracker", "Antigravity", "", 0),
    ]
    for task_name, agent_name, repo_link, satisfied in examples:
        db.execute(
            """
            INSERT INTO task_records
                (task_name, agent_name, repo_link, satisfied, method_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_name, agent_name, repo_link, satisfied, method_id, created, created),
        )


def dashboard_data(filters):
    where = []
    params = []
    if filters["agent_name"]:
        where.append("r.agent_name = ?")
        params.append(filters["agent_name"])
    if filters["status"] == "satisfied":
        where.append("r.satisfied = 1")
    elif filters["status"] == "failed":
        where.append("r.satisfied = 0")
    if filters["method_id"]:
        where.append("m.id = ?")
        params.append(filters["method_id"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    records = query_db(
        f"""
        SELECT r.*, m.name AS method_name
        FROM task_records r
        JOIN instruction_methods m ON m.id = r.method_id
        {where_sql}
        ORDER BY r.created_at DESC, r.id DESC
        """,
        tuple(params),
    )
    methods = query_db("SELECT * FROM instruction_methods ORDER BY name")

    total = len(records)
    satisfied = sum(1 for row in records if row["satisfied"])
    failed = total - satisfied
    satisfaction_rate = round((satisfied / total) * 100) if total else 0

    agent_stats = []
    for agent in AGENTS:
        agent_rows = [row for row in records if row["agent_name"] == agent]
        passed = sum(1 for row in agent_rows if row["satisfied"])
        agent_stats.append(
            {
                "agent": agent,
                "total": len(agent_rows),
                "passed": passed,
                "failed": len(agent_rows) - passed,
                "rate": round((passed / len(agent_rows)) * 100) if agent_rows else 0,
            }
        )

    return {
        "records": records,
        "methods": methods,
        "agent_stats": agent_stats,
        "summary": {
            "total": total,
            "satisfied": satisfied,
            "failed": failed,
            "satisfaction_rate": satisfaction_rate,
        },
        "api_example": api_example(methods),
    }


def api_example(methods):
    method_name = methods[0]["name"] if methods else DEFAULT_METHOD
    return json.dumps(
        {
            "task_name": "Implement feature X",
            "agent_name": "Codex",
            "github_repo_link": "https://github.com/example/repo",
            "satisfied": True,
            "instruction_method": method_name,
        },
        indent=2,
    )


def create_task_record(payload):
    created = now()
    query_db(
        """
        INSERT INTO task_records
            (task_name, agent_name, repo_link, satisfied, method_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["task_name"],
            payload["agent_name"],
            payload["repo_link"],
            payload["satisfied"],
            payload["method_id"],
            created,
            created,
        ),
        commit=True,
    )
    return query_db("SELECT * FROM task_records ORDER BY id DESC LIMIT 1", one=True)


def update_task_record(task_id, payload):
    query_db(
        """
        UPDATE task_records
        SET task_name = ?, agent_name = ?, repo_link = ?, satisfied = ?, method_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            payload["task_name"],
            payload["agent_name"],
            payload["repo_link"],
            payload["satisfied"],
            payload["method_id"],
            now(),
            task_id,
        ),
        commit=True,
    )


def resolve_method(name):
    method_name = str(name or "").strip()
    if not method_name:
        raise ValueError("instruction_method is required")
    row = query_db("SELECT id FROM instruction_methods WHERE name = ?", (method_name,), one=True)
    if row:
        return row["id"]
    query_db(
        "INSERT INTO instruction_methods (name, steps, created_at) VALUES (?, ?, ?)",
        (method_name, "", now()),
        commit=True,
    )
    row = query_db("SELECT id FROM instruction_methods WHERE name = ?", (method_name,), one=True)
    return row["id"]


def export_data():
    return {
        "instruction_methods": [dict(row) for row in query_db("SELECT * FROM instruction_methods ORDER BY id")],
        "task_records": [dict(row) for row in query_db("SELECT * FROM task_records ORDER BY id")],
    }


def import_data(payload):
    required = {
        "instruction_methods": ["id", "name", "created_at"],
        "task_records": ["id", "task_name", "agent_name", "satisfied", "method_id", "created_at"],
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
        db.execute("DELETE FROM task_records")
        db.execute("DELETE FROM instruction_methods")
        insert_rows(db, "instruction_methods", payload["instruction_methods"])
        insert_rows(db, "task_records", payload["task_records"])
        db.execute("PRAGMA foreign_keys = ON")


def insert_rows(db, table, rows):
    if not rows:
        return
    allowed_fields = {
        "instruction_methods": ["id", "name", "steps", "created_at"],
        "task_records": [
            "id",
            "task_name",
            "agent_name",
            "repo_link",
            "satisfied",
            "method_id",
            "created_at",
            "updated_at",
        ],
    }[table]
    for row in rows:
        fields = [field for field in allowed_fields if field in row]
        if table == "task_records" and "updated_at" not in fields:
            row["updated_at"] = row["created_at"]
            fields.append("updated_at")
        placeholders = ", ".join(["?"] * len(fields))
        db.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})",
            tuple(row.get(field) for field in fields),
        )


def require_form(name):
    return clean_required(request.form.get(name), name)


def clean_required(value, name):
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def parse_satisfied(value):
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "satisfied", "pass", "passed"}:
        return 1
    if text in {"0", "false", "no", "n", "not satisfied", "failed", "fail"}:
        return 0
    raise ValueError("satisfied must be true or false")


def now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=True, port=port)

# Coding Agent Task Tracker

Local Flask dashboard for tracking completed coding-agent tasks. The app is intentionally small: the main view shows task records, satisfaction status, instruction method, agent, and an optional GitHub repo link.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PORT=5055 python app.py
```

Open `http://127.0.0.1:5055`.

The app creates `data/evaluations.db` automatically and seeds example records for Codex, Claude Code, Cursor, and Antigravity.

## One-Line Agent Update Command

Give this to a coding agent before it starts work so it knows how to record the result after it finishes. If the instruction method was not already specified, the agent should ask the user what instruction method to record before running the command. After the task is complete, the agent should replace the placeholders, set `satisfied` based on the user's final judgment, run the command, and briefly confirm whether the tracker update succeeded.

```bash
curl -s -X POST http://127.0.0.1:5055/api/tasks -H 'content-type: application/json' -d '{"task_name":"REPLACE_WITH_TASK_NAME","agent_name":"REPLACE_WITH_AGENT_NAME","github_repo_link":"https://github.com/OWNER/REPO","satisfied":true,"instruction_method":"ASK_USER_FOR_INSTRUCTION_METHOD"}'
```

Leave `github_repo_link` as an empty string when there is no repo link.

## Agent API

`POST /api/tasks` accepts JSON:

```json
{
  "task_name": "Implement feature X",
  "agent_name": "Codex",
  "github_repo_link": "https://github.com/example/repo",
  "satisfied": true,
  "instruction_method": "Plan mode first -> complete the task"
}
```

Accepted `satisfied` values include `true`, `false`, `yes`, `no`, `satisfied`, `not satisfied`, `pass`, and `fail`.

If `instruction_method` does not exist yet, the API creates it automatically.

## Manual Use

The dashboard is mainly for viewing records. Manual add/edit controls are hidden under **Add or edit records** so the default page stays uncluttered.

Each task record stores:

- Task name
- Agent name
- Optional GitHub repo link
- Satisfied or not satisfied
- Instruction method
- Created and updated timestamps

## JSON Import and Export

Use **Export JSON** to write and download `data/export.json`. Import expects:

```json
{
  "instruction_methods": [],
  "task_records": []
}
```

Required fields:

- `instruction_methods`: `id`, `name`, `created_at`
- `task_records`: `id`, `task_name`, `agent_name`, `satisfied`, `method_id`, `created_at`

SQLite remains the source of truth. JSON is only for backup and restore.

## Verification

```bash
PYTHONPYCACHEPREFIX=/tmp/compare-agent-pycache python3 -m py_compile app.py
PYTHONPYCACHEPREFIX=/tmp/compare-agent-pycache python3 -m unittest discover -s tests
```

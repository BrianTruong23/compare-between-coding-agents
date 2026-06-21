# Flask Coding Agent Evaluation Dashboard

Local Flask dashboard for comparing how well coding agents satisfy the same project task. It is designed around a manual evaluation workflow for Codex, Claude Code, Cursor, and Antigravity.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

The app creates `data/evaluations.db` automatically and seeds one example project, task, instruction method, and four agent evaluations.

## Data Model

- `projects`: project name, description, created date.
- `tasks`: project, task title, original request, expected outcome, created date.
- `instruction_methods`: reusable method name and steps.
- `evaluations`: task, agent name, instruction method, satisfied flag, confidence score, issue category, notes, repo link, result link, created date.

The default instruction method is `Plan mode first -> complete the task`.

## Evaluation Workflow

1. Ask the coding agent for a concrete plan first.
2. Review the plan for missing requirements, risky assumptions, or vague verification.
3. Ask the agent to complete the task end to end.
4. Manually mark whether the result satisfied your need.
5. Record confidence, issue category, notes, and links so future comparisons separate agent quality from prompting style.

## Dashboard

The dashboard includes:

- Summary cards for total tasks, satisfaction rate, failed evaluations, and pending reviews.
- Per-agent comparison for Codex, Claude Code, Cursor, and Antigravity.
- Issue-frequency breakdown and confidence trend.
- Recent evaluations table.
- Filters by project, agent, status, and instruction method.
- Forms to add or edit projects, tasks, instruction methods, and evaluations.

## JSON Import and Export

Use **Export JSON** to write and download `data/export.json`. Import expects the same top-level schema:

```json
{
  "projects": [],
  "tasks": [],
  "instruction_methods": [],
  "evaluations": []
}
```

Required fields:

- `projects`: `id`, `name`, `created_at`
- `tasks`: `id`, `project_id`, `title`, `created_at`
- `instruction_methods`: `id`, `name`, `created_at`
- `evaluations`: `id`, `task_id`, `agent_name`, `method_id`, `satisfied`, `confidence_score`, `created_at`

JSON backup files are for import/export only. SQLite remains the source of truth.

## Verification

```bash
python -m py_compile app.py
python -m unittest
```

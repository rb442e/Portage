# Portage

**Carry your work across — intact.**

Portage is a self-hosted ALM migration platform. It ingests a source export
(today: Rally), maps it to a target schema (today: Jira), and **creates the work
items live through the target's API** — no CSV importer, hierarchy preserved,
attachments moved in the same pass.

It is a product-grade evolution of this repo's proven scripts
(`rally_to_jira.py`, `add_attachments.py`), wrapped in a ConnectALL-style UI
built specifically for **migrations**.

```
┌─────────────┐    upload    ┌──────────────┐   REST create   ┌──────────┐
│ Rally export│ ───────────▶ │   Portage    │ ──────────────▶ │   Jira   │
│  (.csv)     │              │  transform + │   + links       │  project │
└─────────────┘              │  live create │   + attachments └──────────┘
        ▲ optional Rally API key for live attachment transfer ▲
```

## Why it's different from a CSV import
- **Live creation** via the Jira REST API using an API token — no manual import wizard.
- **Hierarchy preserved**: Epics/Features → Stories → Sub-tasks are created in
  order and linked by an intra-batch id map.
- **Attachments integrated**: pulled from URLs in the export, or live from Rally,
  and uploaded during creation (idempotent — existing files are skipped).
- **Dry-run preview**: see every planned work item and warning before writing.
- **Full audit**: every run is recorded with per-item results.

## Architecture
- `backend/` — FastAPI. Connectors (`jira_client`, `rally_client`), a mapping +
  transform engine, a migration orchestrator, and a SQLite store.
- `frontend/` — React + Vite + TypeScript. A five-screen console: Dashboard,
  Connections, Mapping Studio, Migrate (wizard), Reports.

## Run it locally

### 1. Backend
```bash
cd portage/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

### 2. Frontend
```bash
cd portage/frontend
npm install
npm run dev
```
Open http://localhost:5173 (Vite proxies `/api` to the backend on :8000).

## Using it
1. **Connections** — paste your Jira base URL, email, API token, and project key.
   Click **Test connections**, then **Discover fields** — Portage reads your
   instance and auto-fills Sprint / Story Points / Team / Epic Link / Rally-ID
   custom-field IDs and lists the project's real issue types. (Add a Rally API
   key only if you want live attachment transfer.)
2. **Migrate → Upload** — drop a `jira_all_issues.csv` (produced by the existing
   `rally_to_jira.py`) for a zero-config path, or a raw Rally CSV if you've built
   a template.
3. **Configure** — pick a mapping template (or Auto) and toggle attachments.
4. **Preview** — review the dry run: counts by type, warnings, planned items.
5. **Migrate** — create the items live and watch progress + the live log.
6. **Reports** — revisit any past run's full result table.

## Two input paths
- **Converted export (fast path):** feed the `jira_all_issues.csv` your existing,
  battle-tested `rally_to_jira.py` already produces. The built-in template maps
  it automatically — you get live creation with zero manual mapping.
- **Raw Rally export:** build a reusable template in the **Mapping Studio** that
  matches source columns to Portage's canonical fields.

## Two ways to migrate (chosen at the Preview step)
- **① Create live in Jira** — work items are created directly through the Jira
  REST API, with hierarchy, links and attachments. Needs a verified connection.
- **② Generate Jira import files** — download a consolidated `jira_all_issues.csv`
  plus one CSV per issue type (and a `.zip`) for Jira's built-in CSV importer.
  No credentials required; the mapping + lookups are already applied. In Jira:
  *System → External System Import → CSV*.

## Custom fields
Sprint, Story Points, Team, Epic Link and a Rally-ID stamp are all **configurable
custom-field IDs** per Jira connection, because these vary by Jira instance.
**Discover fields** (Connections tab) reads them straight from your instance via
the Jira `createmeta` + field APIs and pre-fills them — no manual
`customfield_xxxx` hunting. Blank means the field is skipped.

## Security notes
- API tokens live in memory only (frontend) and are passed per request; they are
  never written to disk or localStorage.
- TLS verification uses the OS trust store when `truststore` is installed, so it
  works behind corporate TLS-inspection proxies.
- This MVP has no user auth — run it inside your network / behind SSO. See
  `PRODUCT.md` for the hardening roadmap.

## Deploy (single origin)
Build the frontend and let the API serve it:
```bash
cd portage/frontend && npm run build      # emits frontend/dist
cd ../backend && PORTAGE_FRONTEND_DIST=../frontend/dist uvicorn app.main:app --port 8000
```
Or `docker compose up` (see `docker-compose.yml`).

## Roadmap
See [PRODUCT.md](PRODUCT.md) for the product vision, competitive positioning
against ConnectALL, and the path to a sellable release.

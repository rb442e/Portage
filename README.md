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
Requires Python 3.11+ (the Docker image uses 3.12).
```bash
cd portage/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PORTAGE_ADMIN_EMAILS=you@company.com PORTAGE_AUTH_DEV_LOG_CODES=1 uvicorn app.main:app --reload --port 8000
```
Sign-in is on by default. With `PORTAGE_AUTH_DEV_LOG_CODES=1` and no SMTP server configured, sign-in codes are
printed in the backend console. Use `PORTAGE_AUTH_DISABLED=1` to skip sign-in entirely on a single-user machine.
See [Sign-in and roles](#sign-in-and-roles).
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

## Sora, the Portage assistant
<img src="frontend/public/sora.svg" alt="Sora" width="56" align="right" />

An in-app assistant (the **Ask Sora** button, or `Ctrl/Cmd+K`) that takes plain-English requests such as
"map Rally Iteration to the Jira sprint field for User Story" or "add Sprint 24 (1042) to the
sprint catalog". It runs on a **local Ollama model** (default `llama3.1:8b`), so nothing leaves your machine.
```bash
ollama pull llama3.1:8b      # once; then keep `ollama serve` running
```
- **Propose, then approve:** every change appears as a diff card and is applied only when you click **Apply**.
  Mapping edits are saved as a new `jira_<artifact>_mapping_vN`; catalog edits are versioned (Jira Catalog → History).
- **Redaction on by default:** emails and secrets are masked before reaching the model (⚙ in the panel to change).
- **Skills:** `@mapping`, `@catalog`, `@migration`, `@guide`, `@lineage`. Modes, model and URL are configurable in ⚙
  or via `PORTAGE_OLLAMA_URL`, `PORTAGE_COPILOT_MODEL`, `PORTAGE_COPILOT_MODE`.
- **Skill files:** each skill is a versioned Markdown file at
  [`backend/app/copilot/skills/`](backend/app/copilot/skills/). Its YAML front matter defines selection keywords,
  routes, suggestions, and allowed tools; its Markdown body contains Sora’s instructions. Portage validates the
  complete skill set when it starts.
- Tests: `cd backend && pip install pytest httpx && pytest tests` (add `PORTAGE_LIVE_LLM=1` to also run the checks against your local Ollama model).

### Give Sora context: files and screenshots
Like Rovo, Sora can use what you show it. In the Sora panel, attach with the paperclip, drag a file in, paste a
screenshot (`Cmd/Ctrl+V`) or use the camera button to capture your screen or a window. A chip also shows which page
Sora can see.
- **Files:** `.txt .md .csv .tsv .json .log .yaml .yml .xml .sql` up to 2 MB. CSVs are summarised (row count, columns,
  first rows). Text is masked like chat text.
- **Screenshots:** PNG, JPEG, GIF or WebP up to 5 MB. A local **vision model** reads the image once and Sora answers from
  its description, because vision models rarely support tools. Install one with `ollama pull gemma3:4b` (about 3 GB; read
  a test screenshot correctly in about 14 s) and set it in **Settings → Sora assistant** (or `PORTAGE_VISION_MODEL`).
  Not every vision model runs on every Ollama build: `llama3.2-vision` fails to load on Ollama 0.40 ("unknown model
  architecture 'mllama'"), so pick another if yours does. Text inside a screenshot cannot be masked; it only goes to
  your local model.
- **Safety:** files are checked by content, not name (no SVG or HTML, no binaries); attached text is treated as untrusted
  data, and changes still need your click on Apply. Chat history keeps names only. Files are deleted after
  **Keep attachments (days)**, default 7. Follow-up questions keep earlier attachments in context, within a size budget.

### GraphRAG: ask how things relate
A knowledge graph is built from your own data on every question (no LLM extraction, so it is exact and always current):
mappings and their versions, Rally → Jira field lineage per artifact, value maps, catalogs with entries and history,
uploaded columns, jobs and error clusters (linked to the catalogs and fields they mention). `graph_search` finds the
best-matching items, follows their relationships for a few hops and adds the relevant documentation;
`graph_overview` summarises the whole workspace. Try `@lineage Which Rally fields feed the sprint field for User Story?`
or `@lineage Which catalogs are affected by the failures in my last job?`.

### MCP server: let other agents use Portage
The same governed tool registry is available to any MCP client (VS Code, Claude Desktop, ...) over stdio:
```bash
PYTHONPATH=backend PORTAGE_DATA_DIR=backend/data .venv/bin/python -m app.mcp_server
```
In VS Code the repo already ships [.vscode/mcp.json](.vscode/mcp.json); start the `portage` server from the MCP list.
Governance is identical to Sora: read tools run immediately, `propose_*` tools only create a proposal you apply in
**Ask Sora → History** (there is no apply tool over MCP), read-only mode hides write tools, redaction masks emails
and secrets, and every call is audited. Requires `mcp>=1.9,<2` (the 2.x SDK changed its server API).
What MCP clients may do is set under **Settings → MCP server**: switch access off, make it read-only (it is also
read-only whenever Sora is), hide individual tools, and choose redaction (on by default, independent of Sora).
The same page shows ready-to-paste client configuration for your installation.

Sora can also use tools from up to eight **local stdio or remote MCP servers** (Streamable HTTP or SSE), managed
under **Settings → MCP server → External MCP servers**. Each server shows its connection status and read-only tools.
Use the server switch to enable or disable all its tools, or expand **Tools available to Sora** to control each tool
individually. **Test**, **Edit** and **Remove** actions are available for servers managed in Settings.

**Add server** opens a form for the command, arguments, working directory and environment variables, with starter
templates and a **Test connection** button that starts the server once before anything is saved. Environment values
are encrypted at rest (`secretbox`), are never returned by the API and are left out of the audit log.

Starting a server runs a program on the machine hosting Portage, so **adding, editing and removing servers is limited
to admins when sign-in is on**. With sign-in off (`PORTAGE_AUTH_DISABLED=1`) it needs
`PORTAGE_ALLOW_MCP_SERVER_EDITING=1`; set that variable to `0` to lock it for everyone. When locked the panel is
read-only and the API answers `403`.

Administrators can still define servers in the environment, which is never editable from the UI and whose command is
never shown. For example:
```bash
export PORTAGE_EXTERNAL_MCP_SERVERS='[{"name":"docs","command":"/opt/portage-mcp-docs/.venv/bin/python","args":["-m","docs_server"]},{"name":"inventory","command":"/opt/inventory-mcp/.venv/bin/python","args":["-m","inventory_server"],"cwd":"/opt/inventory-mcp"}]'
export PORTAGE_MCP_EXTERNAL_SERVERS=docs,inventory
```
Only tools that explicitly advertise `readOnlyHint=true` are offered to Sora, under names such as
`ext_docs__search`. External write-capable or unannotated tools are excluded. MCP annotations are supplied by the
server and are not a security boundary: add only trusted server programs, review their code, and remember
that tool arguments (including unmasked data restored from placeholders) are sent to the server process.

### Settings
The **Settings** page (sidebar) holds product settings in sections: **Sora assistant**, **MCP server**, **GraphRAG**
(default depth and answer size) and a read-only **System** view (data directory, database, CORS, version).
For every setting a saved value wins over an environment variable, which wins over the default; the page shows which
applies and lets you reset to it. Changes are audited. No secrets are kept here. API: `GET /api/settings`,
`PUT /api/settings/{section}`, `DELETE /api/settings/{section}[/{key}]`. To add a setting, add a `Field` in
[backend/app/product_settings.py](backend/app/product_settings.py); the API and page pick it up.

### Sign-in and roles
The sign-in screen has three flows:
- **Sign in** with email and password, or choose **Email me a sign-in code** to get a one-time code instead.
- **Create account** asks for a name, email and password, then emails a 6-digit code to confirm the address. People
  in an allowed domain (or in `PORTAGE_ADMIN_EMAILS`, or already added by an admin) are signed in right away. Anyone
  else becomes an **access request** that admins approve, with a role, or decline on the **Users** page; the person is
  emailed either way, and admins are emailed when a request arrives. `PORTAGE_SIGNUP=off` allows only the first group.
- **Forgot password** emails a reset code. Setting a new password signs the account out on every other device.

Passwords need at least 10 characters, common and repetitive ones are refused, and they are stored with scrypt.
Five wrong passwords lock that account's password sign-in for 15 minutes. Codes last 10 minutes, work once and are
locked after 5 wrong tries. Each address gets at most 5 codes an hour, at least 30 s apart. Sign-up, reset and code
requests give the same answer whether or not an account exists, so nobody can probe who has access. Codes and session
tokens are stored only as hashes. The session is an `HttpOnly`, `SameSite=Lax` cookie, and cross-site writes are rejected.

| Role | Can do |
|---|---|
| **Admin** | Everything, plus **Users**, **Settings**, saved connections, MCP servers and the Sora audit log |
| **Team member** | Run migrations and exports, edit mappings and catalogs, apply Sora's proposals |
| **Viewer** | View everything and ask Sora questions (Sora gets read-only tools only); cannot change anything |

Who can sign in:
- addresses in `PORTAGE_ADMIN_EMAILS`, which are always admins (use this to create the first admin);
- people an admin adds on the **Users** page, with any role;
- anyone whose domain is in `PORTAGE_ALLOWED_EMAIL_DOMAINS`, who starts as a Viewer.

Admins change roles, disable or remove people on the **Users** page. Changes apply on the person's next request, and
disabling someone ends their sessions. Portage keeps at least one active admin, and admins cannot change their own access.

| Variable | Purpose |
|---|---|
| `PORTAGE_SMTP_HOST`, `PORTAGE_SMTP_PORT` (587) | Mail server used to send codes |
| `PORTAGE_SMTP_USER`, `PORTAGE_SMTP_PASSWORD`, `PORTAGE_SMTP_FROM` | Login and sender address |
| `PORTAGE_SMTP_SSL=1` / `PORTAGE_SMTP_STARTTLS=0` | Implicit TLS on 465 / turn off STARTTLS |
| `PORTAGE_ADMIN_EMAILS`, `PORTAGE_ALLOWED_EMAIL_DOMAINS` | Comma-separated lists, as above |
| `PORTAGE_SESSION_HOURS` (168) | How long a sign-in lasts |
| `PORTAGE_SIGNUP` (`request`) | `off` stops sign-ups from outside the allowed domains |
| `PORTAGE_COOKIE_SECURE=1` | Mark the cookie `Secure` when TLS ends at a proxy |
| `PORTAGE_AUTH_DEV_LOG_CODES=1` | Development only: print codes in the server log when no SMTP host is set |
| `PORTAGE_AUTH_DISABLED=1` | Turn sign-in off (everyone is an admin); only for a single-user machine |

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
- Everyone signs in with an emailed one-time code and gets a role (see [Sign-in and roles](#sign-in-and-roles)).
  Serve Portage over HTTPS in production so the session cookie is never sent in clear text.

## Deploy (single origin)
Build the frontend and let the API serve it:
```bash
cd portage/frontend && npm run build      # emits frontend/dist
cd ../backend && PORTAGE_FRONTEND_DIST=../frontend/dist uvicorn app.main:app --port 8000
```
Or `docker compose up` (see `docker-compose.yml`).

## Developer verification

The project-local [verify-portage skill](.agents/skills/verify-portage/SKILL.md) provides isolated runtime checks and a maintained feature map for MCP and Sora behavior:

```bash
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py doctor
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py run mcp
uv run --with playwright python .agents/skills/verify-portage/scripts/verify_portage.py run local
```

The browser group needs Playwright Chromium (`uv run --with playwright python -m playwright install chromium`). It builds the current frontend into a fresh temporary directory. Reports and screenshots/traces survive process cleanup; the command prints their location. `sora-web` and `failed-fetch` are separate opt-in groups requiring local Ollama; `sora-web` also calls live Parallel MCP. A missing prerequisite is blocked, and generated failure explanations require review rather than receiving an automatic pass. See the skill for exit codes and exact coverage.

## Roadmap
See [PRODUCT.md](PRODUCT.md) for the product vision, competitive positioning
against ConnectALL, and the path to a sellable release.

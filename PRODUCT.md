# Portage — Product Blueprint

> Carry your work across — intact.
> A purpose-built ALM/DevOps **migration** platform.

## 1. Positioning

ConnectALL is an excellent **integration/synchronization** platform: it keeps two
live systems continuously in sync (bi-directional, conflict resolution, near
real-time). That is a big, heavy, expensive category.

Most teams changing tools don't need perpetual sync — they need a **clean,
trustworthy, one-time (or phased) migration**. That job is under-served,
error-prone, and usually done with brittle scripts and CSV importers.

**Portage owns the migration niche.** It borrows ConnectALL's best UX ideas —
a visual mapping studio, connectors, business rules, dashboards — but optimizes
every screen for *moving* work, not *syncing* it.

| | ConnectALL (integration) | **Portage (migration)** |
|---|---|---|
| Core job | Keep two live systems in sync forever | Move data once/phased, verifiably |
| Success metric | Sync latency, conflict handling | Fidelity: nothing lost, hierarchy + attachments intact |
| Killer features | Bi-directional flows, conflict rules | Dry-run preview, hierarchy preservation, attachment transfer, reconciliation report |
| Buyer | Platform/tools team, ongoing | Migration lead / PMO, project-based |
| Pricing shape | Per-connection subscription | Per-migration / per-record + support |

**One-line pitch:** *"The safest way to move your backlog to a new tool — preview
everything, migrate live, prove nothing was lost."*

## 2. Who it's for
- **Migration lead / PMO** running a Rally→Jira (or Jira→Jira, ADO→Jira) cutover.
- **Delivery/agile coaches** consolidating many teams onto one platform.
- **SI / consulting partners** who run migrations repeatedly and want a repeatable,
  brandable tool instead of one-off scripts.

## 3. Product principles (UX)
1. **Preview before you write.** Every destructive action has a dry run. Trust is
   the product.
2. **Never lose the source.** Read-only on inputs; re-runnable and idempotent.
3. **Explain every decision.** Warnings are specific and actionable, not generic.
4. **Progressive disclosure.** Simple by default (Auto mapping); power under
   "Advanced".
5. **Prove the outcome.** Every run ends in a reconciliation report you can hand
   to an auditor.

## 4. What's built (MVP, this repo)
- FastAPI backend: Jira + Rally connectors, mapping/transform engine, migration
  orchestrator (hierarchy-aware, links, attachments), SQLite store, background jobs.
- React console: Dashboard, Connections, Mapping Studio, Migrate wizard
  (Upload → Configure → Preview → Migrate), Reports.
- **Live Jira creation via API token** (ADF for Cloud, plain for DC), configurable
  custom fields, idempotent attachment transfer, dry-run preview, per-item audit.
- Reuses the proven transformation of `rally_to_jira.py` (via its converted export)
  and the attachment logic of `add_attachments.py`.

## 5. Roadmap to a sellable release

### Now → Beta (harden the core)
- [ ] **Native Rally transform in-app** (ingest raw Rally CSV directly; port the
      description-normalization + value maps from `rally_to_jira.py` into the engine).
- [x] **Field discovery**: read Jira `createmeta` + field APIs to auto-list issue
      types and suggest custom-field IDs (Sprint / Story Points / Team / Epic Link /
      Rally ID) — no manual `customfield_xxxx` hunting.
- [ ] **Rate limiting + resumable runs**: checkpoint like `add_attachments.py`'s
      batch-state so large migrations resume after interruption.
- [ ] **Reconciliation report**: source vs target counts, missing items, a CSV +
      PDF the customer can sign off on (reuse `validate_migration.py`, `md_to_pdf.py`).
- [ ] **Auth**: OIDC/SAML SSO + roles (admin, operator, viewer).

### Beta → GA (make it a platform)
- [ ] **Connector SDK**: pluggable source/target adapters (Azure DevOps, GitHub
      Issues, Jira→Jira, Trello, Asana). Each is a small class implementing
      `read()` / `create()` / `attach()`.
- [ ] **Mapping marketplace**: shareable, versioned mapping templates (Rally→Jira,
      ADO→Jira) shipped as presets.
- [ ] **Waves/phased migration**: migrate by project/train/sprint in scheduled waves
      with per-wave sign-off.
- [ ] **Delta/backfill mode**: re-run to migrate only new/changed source items
      (bridges toward light sync without becoming ConnectALL).
- [ ] **Comments & history** transfer, user-account matching UI, watchers/votes.

### GA → Scale
- [ ] Multi-tenant SaaS option (per-tenant isolation, billing, usage metering).
- [ ] Observability (OpenTelemetry), horizontal workers (Celery/RQ + Redis).
- [ ] SOC 2 posture: audit logs, secret vaulting (never persist tokens), PII controls.

## 6. Monetization
- **Self-hosted license** (annual) tiered by records migrated / connectors enabled.
- **Per-migration packs** for one-off cutovers (SI-friendly).
- **Support & success**: guided migration, custom connectors, done-with-you.
- **Marketplace**: paid premium connectors and certified mapping templates.

## 7. Brand system
- **Name:** Portage — a portage is the act of carrying boats/cargo overland between
  two navigable waters. Perfect migration metaphor: cross the gap, arrive intact.
- **Tagline:** *Carry your work across — intact.*
- **Voice:** calm, precise, trustworthy (this is high-stakes data movement).
- **Visual:** deep navy + indigo→cyan gradient (see the app). Rounded, spacious,
  dashboard-first. Alt names if trademark clearance is needed: *Ferrywork,
  Crosswork, Relayent, Transomic.*

## 8. Risks & mitigations
- **Jira field variance** → `createmeta` discovery + per-connection field config.
- **Rate limits / large volumes** → batching, backoff, resumable checkpoints.
- **User/account mapping** → dedicated matching UI + CSV import (from `user_mapping.csv`).
- **Trust** → dry-run + reconciliation report are non-negotiable, first-class features.
- **Scope creep toward sync** → stay migration-first; "delta mode" is the only
  concession, and it's still initiated, not continuous.

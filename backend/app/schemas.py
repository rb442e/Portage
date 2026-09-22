"""Pydantic request/response models shared across routers and the engine."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
class JiraConnection(BaseModel):
    base_url: str = Field(..., description="e.g. https://your-org.atlassian.net")
    email: str = ""
    api_token: str = ""
    deployment: str = "cloud"  # "cloud" (ADF, accountId) or "server" (plain, name)
    project_key: str = ""

    # Instance-specific custom field ids (optional). Left blank => field skipped.
    sprint_field: str = ""          # e.g. customfield_10020
    story_points_field: str = ""    # e.g. customfield_10016
    team_field: str = ""            # e.g. customfield_10001
    epic_link_field: str = ""       # classic company-managed epic link; blank => use `parent`
    rally_id_field: str = ""        # to stamp the source id onto the created issue


class RallyConnection(BaseModel):
    base_url: str = "https://rally1.rallydev.com"
    api_key: str = ""
    project_object_id: str = ""   # optional Rally Project ObjectID; scopes lookups to that project only


class ConnectionTestRequest(BaseModel):
    jira: Optional[JiraConnection] = None
    rally: Optional[RallyConnection] = None


class ConnectionTestResult(BaseModel):
    system: str
    ok: bool
    detail: str = ""
    account: str = ""


# Saved connection profile (persisted server-side; secrets encrypted at rest).
class SavedConnectionRequest(BaseModel):
    jira: JiraConnection
    rally: RallyConnection


class SavedConnectionState(BaseModel):
    saved: bool = False
    saved_at: str = ""
    jira: Optional[JiraConnection] = None
    rally: Optional[RallyConnection] = None


# ---------------------------------------------------------------------------
# Jira schema discovery (createmeta + field catalog)
# ---------------------------------------------------------------------------
class JiraMetaField(BaseModel):
    id: str
    name: str
    custom: bool = False
    schema_custom: str = ""


class JiraIssueType(BaseModel):
    id: str
    name: str
    subtask: bool = False


class DiscoverRequest(BaseModel):
    jira: JiraConnection


class JiraMetaResult(BaseModel):
    issue_types: List[JiraIssueType] = []
    custom_fields: List[JiraMetaField] = []
    suggestions: Dict[str, str] = {}
    warnings: List[str] = []


# ---------------------------------------------------------------------------
# Sources / uploads
# ---------------------------------------------------------------------------
class SourcePreview(BaseModel):
    source_id: str
    filename: str
    kind: str                    # "rally_export" | "jira_all_issues"
    row_count: int
    columns: List[str]
    sample: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Mapping model
# ---------------------------------------------------------------------------
class FieldMap(BaseModel):
    source: str = ""             # single source column (back-compat)
    sources: List[str] = []      # ordered coalesce: first non-empty column wins
    source_type: str = ""        # Rally-side data type (informational/validation)
    target: str                  # normalized/target field name
    target_type: str = ""        # Jira-side data type
    transform: str = ""          # optional named transform: date|labels|number
    note: str = ""               # optional human note (e.g. "via value map")


class ValueMap(BaseModel):
    field: str                   # target field this value map applies to (status/priority/...)
    values: Dict[str, str] = {}  # source value -> target value


class MappingTemplate(BaseModel):
    id: Optional[int] = None
    name: str
    description: str = ""
    version: int = 1
    issue_type_field: str = "Issue Type"
    field_maps: List[FieldMap] = []                    # fallback for untyped rows
    profiles: Dict[str, List[FieldMap]] = {}           # per artifact type: full field list
    value_maps: List[ValueMap] = []


class CanonicalFieldDef(BaseModel):
    field: str
    label: str
    data_type: str               # string|text|number|date|user|option|array|id


class LegacyImportResult(BaseModel):
    template: MappingTemplate
    notes: List[str] = []


class GeneratedCode(BaseModel):
    filename: str
    code: str
    language: str = "python"


# ---------------------------------------------------------------------------
# Jira Catalog — reusable value mappings (sprint / version / user / team)
#
# Each catalog is one simple source-value -> target-value table for a kind. At
# migration time it translates Rally values to their Jira equivalents (sprint /
# version names or IDs, user emails, team IDs). `side` is retained for storage
# backward-compatibility and defaults to "rally_to_jira".
# ---------------------------------------------------------------------------
LOOKUP_KINDS = ("sprint", "version", "user", "team")
LOOKUP_SIDES = ("rally_to_jira", "jira_catalog")


class LookupTable(BaseModel):
    id: Optional[int] = None
    name: str
    kind: str                    # one of LOOKUP_KINDS
    side: str = "rally_to_jira"  # retained for storage back-compat
    entries: Dict[str, str] = {}  # Rally value -> Jira value


class LookupCsvPreview(BaseModel):
    columns: List[str]
    sample: List[Dict[str, Any]]
    suggested_source: str = ""
    suggested_target: str = ""


# ---------------------------------------------------------------------------
# Normalized issue (system-agnostic intermediate representation)
# ---------------------------------------------------------------------------
class NormalizedIssue(BaseModel):
    row_id: str = ""            # intra-batch id used to resolve parent links
    parent_row_id: str = ""     # points at another issue's row_id
    external_id: str = ""       # source-system id (Rally FormattedID) for stamping/attachments
    parent_external_id: str = ""
    issue_type: str = ""
    summary: str = ""
    description: str = ""
    status: str = ""
    priority: str = ""
    assignee: str = ""
    reporter: str = ""
    labels: List[str] = []
    components: List[str] = []
    story_points: Optional[float] = None
    sprint: str = ""
    team: str = ""
    fix_versions: List[str] = []
    start_date: str = ""
    due_date: str = ""
    links: List[str] = []
    attachments: List[Dict[str, str]] = []  # {name, url|ref}
    extra: Dict[str, Any] = {}              # non-core Jira fields (Epic Name, Severity, ...)
    raw: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Migration preview / run
# ---------------------------------------------------------------------------
class MigrationRequest(BaseModel):
    source_id: str
    jira: JiraConnection
    rally: Optional[RallyConnection] = None
    mapping_id: Optional[int] = None
    mapping: Optional[MappingTemplate] = None   # inline field mapping (raw path)
    force_type: Optional[str] = None            # apply this profile to every row (single-type files)
    lookup_ids: List[int] = []
    type_map: Dict[str, str] = {}   # normalized type -> Jira issue type name
    include_attachments: bool = True
    dry_run: bool = False
    migration_id: Optional[str] = None          # correlates preview/export/run of one workflow
    parent_map_id: Optional[str] = None         # uploaded parent.csv (Rally ID -> Jira Issue id) for Parent Id VLOOKUP
    split_rows: int = 0                          # >0 splits per-type export files into part files of this size


# ---------------------------------------------------------------------------
# Batch (multi-file, per-artifact) Rally extract
# ---------------------------------------------------------------------------
class BatchFileItem(BaseModel):
    source_id: str
    artifact_type: str = ""      # Epic | Feature | User Story | Task | Defect


class BatchUploadItem(BaseModel):
    source_id: str
    filename: str
    artifact_type: str = ""
    row_count: int = 0
    columns: List[str] = []
    warnings: List[str] = []


class BatchUploadResult(BaseModel):
    items: List[BatchUploadItem] = []


class BatchMigrationRequest(BaseModel):
    files: List[BatchFileItem] = []
    jira: Optional[JiraConnection] = None
    mapping_id: Optional[int] = None
    mapping: Optional[MappingTemplate] = None
    lookup_ids: List[int] = []
    type_map: Dict[str, str] = {}
    include_attachments: bool = True
    migration_id: Optional[str] = None
    parent_map_id: Optional[str] = None
    split_rows: int = 0


class MappingIssue(BaseModel):
    catalog: str                 # user | team | sprint
    field: str                   # human field label
    mapping_file: str            # user_mapping | team_mapping | sprint_mapping
    catalog_loaded: bool = True  # is that catalog selected/loaded at all
    missing_values: List[str] = []
    missing_count: int = 0
    affected_rows: int = 0


class MappingValidation(BaseModel):
    ok: bool = True
    total_missing: int = 0
    issues: List[MappingIssue] = []


class PlannedIssue(BaseModel):
    external_id: str
    parent_external_id: str = ""
    jira_issue_type: str
    summary: str
    warnings: List[str] = []
    fields_preview: Dict[str, Any] = {}

class PreviewResult(BaseModel):
    source_id: str
    total: int
    by_type: Dict[str, int]
    planned: List[PlannedIssue]
    warnings: List[str] = []
    parents_resolved: int = 0
    parents_total: int = 0


class ExportFile(BaseModel):
    name: str
    rows: int


class ExportResult(BaseModel):
    export_id: str
    total: int
    migration_id: str = ""
    files: List[ExportFile] = []


class ExportRecord(BaseModel):
    export_id: str
    created_at: str = ""
    total: int = 0
    kind: str = ""               # "single" | "batch"
    label: str = ""              # source filename or "N files"
    migration_id: str = ""       # workflow correlation id
    files: List[ExportFile] = []


class ParentMapResult(BaseModel):
    parent_map_id: str
    filename: str
    row_count: int = 0
    key_column: str = ""         # the Rally-ID column
    value_column: str = ""       # the Jira Issue-id column
    count: int = 0               # distinct Rally IDs mapped
    sample: List[Dict[str, str]] = []


class ExportPreview(BaseModel):
    file: str
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    total_rows: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------
# Standalone tools (outside the migration workflow) — CSV file splitter
# ---------------------------------------------------------------------------
class SplitPart(BaseModel):
    name: str
    rows: int
    size: int = 0                # part file size in bytes


class SplitResult(BaseModel):
    split_id: str
    filename: str
    parts: List[SplitPart] = []
    total_rows: int = 0
    total_size: int = 0          # combined size of all parts in bytes


# ---------------------------------------------------------------------------
# Standalone tool — copy a Rally description (with tables) into a Jira issue
# ---------------------------------------------------------------------------
class CopyDescriptionRequest(BaseModel):
    jira: JiraConnection
    rally: RallyConnection
    rally_id: str                # Rally FormattedID, e.g. F139943
    jira_key: str = ""           # target Jira issue key, e.g. PN-123 (required to apply)


class CopyDescriptionResult(BaseModel):
    rally_id: str
    jira_key: str = ""
    format: str = ""             # "adf" (Cloud) | "wiki" (Server/DC)
    tables_found: int = 0
    has_source: bool = False     # Rally returned a non-empty description
    applied: bool = False        # written to Jira (apply) vs. preview only
    message: str = ""
    text_preview: str = ""       # readable preview (wiki markup or flattened ADF)


# Bulk copy-description (over a list of Rally IDs). Dry-run = table-detection report.
class CopyDescIdsResult(BaseModel):
    filename: str
    row_count: int = 0
    id_column: str = ""
    key_column: str = ""                # Jira key/id column, if the CSV is a post-import map
    rally_ids: List[str] = []
    id_map: Dict[str, str] = {}         # rally_id -> Jira key/id (when key_column present)


class CopyDescBulkRequest(BaseModel):
    jira: JiraConnection
    rally: RallyConnection
    rally_id_field: str = "Rally ID"   # Jira field/id carrying the Rally FormattedID
    rally_ids: List[str] = []
    id_map: Dict[str, str] = {}        # optional rally_id -> Jira key/id; used before JQL lookup
    dry_run: bool = False              # detect + report only, no write
    tables_only: bool = False          # when applying, only write descriptions containing a table


class CopyDescItemResult(BaseModel):
    rally_id: str
    jira_key: str = ""
    tables_found: int = 0
    status: str = ""    # dry-run | applied | skipped | empty | error | unresolved
    detail: str = ""


class CopyDescJob(BaseModel):
    job_id: str
    state: str = "queued"        # queued | running | done | failed
    dry_run: bool = False
    tables_only: bool = False
    total_ids: int = 0
    processed_ids: int = 0
    resolved: int = 0
    unresolved: int = 0
    with_tables: int = 0
    applied: int = 0
    skipped: int = 0
    empty: int = 0
    errors: int = 0
    progress: float = 0.0
    log: List[str] = []
    items: List[CopyDescItemResult] = []
    started_at: str = ""
    finished_at: str = ""


class JobItemResult(BaseModel):
    external_id: str
    jira_key: str = ""
    status: str = "pending"      # pending|created|linked|attached|failed|skipped
    message: str = ""
    attachments_uploaded: int = 0


class JobStatus(BaseModel):
    job_id: str
    state: str = "queued"        # queued|running|done|failed
    dry_run: bool = False
    migration_id: str = ""
    total: int = 0
    created: int = 0
    failed: int = 0
    skipped: int = 0
    attachments_uploaded: int = 0
    progress: float = 0.0
    log: List[str] = []
    items: List[JobItemResult] = []
    started_at: str = ""
    finished_at: str = ""


# ---------------------------------------------------------------------------
# Attachments (post-migration: push Rally attachments onto existing Jira issues)
# ---------------------------------------------------------------------------
class AttachmentIdsResult(BaseModel):
    filename: str
    row_count: int = 0
    id_column: str = ""
    rally_ids: List[str] = []


class AttachmentRunRequest(BaseModel):
    jira: JiraConnection
    rally: RallyConnection
    rally_id_field: str = "Rally ID"     # Jira field/id that carries the Rally FormattedID
    rally_ids: List[str] = []
    dry_run: bool = False


class AttachmentItemResult(BaseModel):
    rally_id: str
    jira_key: str = ""
    file_name: str = ""
    source: str = ""
    status: str = ""      # uploaded | exists | skipped | error | dry-run | no attachments
    detail: str = ""


class AttachmentJob(BaseModel):
    job_id: str
    state: str = "queued"        # queued | running | done | failed
    dry_run: bool = False
    total_ids: int = 0
    processed_ids: int = 0
    resolved: int = 0
    unresolved: int = 0
    uploaded: int = 0
    exists: int = 0
    skipped: int = 0
    errors: int = 0
    progress: float = 0.0
    log: List[str] = []
    items: List[AttachmentItemResult] = []
    started_at: str = ""
    finished_at: str = ""

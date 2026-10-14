// Shared types mirroring the backend Pydantic schemas.

export interface JiraConnection {
  base_url: string;
  email: string;
  api_token: string;
  deployment: "cloud" | "server";
  project_key: string;
  sprint_field: string;
  story_points_field: string;
  team_field: string;
  epic_link_field: string;
  rally_id_field: string;
}

export interface RallyConnection {
  base_url: string;
  api_key: string;
  project_object_id?: string;
}

export interface SavedConnectionState {
  saved: boolean;
  saved_at: string;
  jira: JiraConnection | null;
  rally: RallyConnection | null;
}

export interface ConnectionTestResult {
  system: string;
  ok: boolean;
  detail: string;
  account: string;
}

export interface JiraMetaField {
  id: string;
  name: string;
  custom: boolean;
  schema_custom: string;
}

export interface JiraIssueType {
  id: string;
  name: string;
  subtask: boolean;
}

export interface JiraMetaResult {
  issue_types: JiraIssueType[];
  custom_fields: JiraMetaField[];
  suggestions: Record<string, string>;
  warnings: string[];
}

export interface SourcePreview {
  source_id: string;
  filename: string;
  kind: string;
  row_count: number;
  columns: string[];
  sample: Record<string, any>[];
}

export interface FieldMap {
  source?: string;
  sources?: string[];
  source_type?: string;
  target: string;
  target_type?: string;
  transform?: string;
  note?: string;
}
export interface ValueMap { field: string; values: Record<string, string>; }
export interface MappingTemplate {
  id?: number;
  name: string;
  description: string;
  version?: number;
  issue_type_field: string;
  field_maps: FieldMap[];
  profiles?: Record<string, FieldMap[]>;
  value_maps: ValueMap[];
}

export interface CatalogField { key: string; label: string; data_type: string; }
export interface MappingCatalog {
  artifacts: string[];
  common: { rally: CatalogField[]; jira: CatalogField[] };
  specific: Record<string, { rally: CatalogField[]; jira: CatalogField[] }>;
  defaults: Record<string, { source: string; target: string }[]>;
}

export interface GeneratedCode { filename: string; code: string; language: string; }

export interface CanonicalFieldDef { field: string; label: string; data_type: string; }
export interface LegacyImportResult { template: MappingTemplate; notes: string[]; }

export type LookupKind = "sprint" | "version" | "user" | "team";
export interface LookupTable {
  id?: number;
  name: string;
  kind: LookupKind;
  side?: string;
  entries: Record<string, string>;
}
export interface LookupVersion { version: number; author: string; message: string; created_at: string; size: number; }

export type SettingValue = boolean | number | string | string[];
export interface SettingsField {
  key: string; label: string; type: "bool" | "int" | "text" | "choice" | "multi"; help: string; env: string;
  default: SettingValue; value: SettingValue; source: "saved" | "env" | "default";
  choices: string[]; labels: Record<string, string>; min: number | null; max: number | null;
}
export interface SettingsSection { key: string; label: string; summary: string; fields: SettingsField[]; }
export interface SettingsView {
  sections: SettingsSection[];
  system: { label: string; value: string; env: string }[];
  effective_mcp: { enabled: boolean; redact: boolean; read_only: boolean; hidden_tools: string[] };
}
export interface McpConnection { transport: string; shell: string; vscode: string; generic: string; }
export interface EntryDiff {
  added: Record<string, string>;
  removed: Record<string, string>;
  changed: Record<string, { from: string; to: string }>;
  summary: string;
  from_version?: number;
  to_version?: number;
}
export interface LookupCsvPreview {
  columns: string[];
  sample: Record<string, any>[];
  suggested_source: string;
  suggested_target: string;
}

export interface PlannedIssue {
  external_id: string;
  parent_external_id: string;
  jira_issue_type: string;
  summary: string;
  warnings: string[];
  fields_preview: Record<string, any>;
}

export interface PreviewResult {
  source_id: string;
  total: number;
  by_type: Record<string, number>;
  planned: PlannedIssue[];
  warnings: string[];
  parents_resolved?: number;
  parents_total?: number;
}

export interface ParentMapResult {
  parent_map_id: string;
  filename: string;
  row_count: number;
  key_column: string;
  value_column: string;
  count: number;
  sample: { rally_id: string; issue_id: string }[];
}

export interface ExportFile {
  name: string;
  rows: number;
}
export interface ExportResult {
  export_id: string;
  total: number;
  migration_id: string;
  files: ExportFile[];
}

export interface BatchUploadItem {
  source_id: string;
  filename: string;
  artifact_type: string;
  row_count: number;
  columns: string[];
  warnings: string[];
}
export interface BatchUploadResult {
  items: BatchUploadItem[];
}
export interface BatchFileItem {
  source_id: string;
  artifact_type: string;
}

export interface ExportRecord {
  export_id: string;
  created_at: string;
  total: number;
  kind: string;
  label: string;
  migration_id: string;
  files: ExportFile[];
}
export interface ExportPreview {
  file: string;
  columns: string[];
  rows: Record<string, any>[];
  total_rows: number;
  truncated: boolean;
}

export interface SplitPart {
  name: string;
  rows: number;
  size: number;
}
export interface SplitResult {
  split_id: string;
  filename: string;
  parts: SplitPart[];
  total_rows: number;
  total_size: number;
}

export interface CopyDescriptionResult {
  rally_id: string;
  jira_key: string;
  format: string;
  tables_found: number;
  has_source: boolean;
  applied: boolean;
  message: string;
  text_preview: string;
}

export interface CopyDescIdsResult {
  filename: string;
  row_count: number;
  id_column: string;
  key_column: string;
  rally_ids: string[];
  id_map: Record<string, string>;
}
export interface CopyDescItemResult {
  rally_id: string;
  jira_key: string;
  tables_found: number;
  status: string;
  detail: string;
}
export interface CopyDescJob {
  job_id: string;
  state: string;
  dry_run: boolean;
  tables_only: boolean;
  total_ids: number;
  processed_ids: number;
  resolved: number;
  unresolved: number;
  with_tables: number;
  applied: number;
  skipped: number;
  empty: number;
  errors: number;
  progress: number;
  log: string[];
  items: CopyDescItemResult[];
  started_at: string;
  finished_at: string;
}

export interface MappingIssue {
  catalog: string;
  field: string;
  mapping_file: string;
  catalog_loaded: boolean;
  missing_values: string[];
  missing_count: number;
  affected_rows: number;
}
export interface MappingValidation {
  ok: boolean;
  total_missing: number;
  issues: MappingIssue[];
}

export interface JobItemResult {
  external_id: string;
  jira_key: string;
  status: string;
  message: string;
  attachments_uploaded: number;
}

export interface JobStatus {
  job_id: string;
  state: string;
  dry_run: boolean;
  migration_id?: string;
  total: number;
  created: number;
  failed: number;
  skipped: number;
  attachments_uploaded: number;
  progress: number;
  log: string[];
  items: JobItemResult[];
  started_at: string;
  finished_at: string;
}

export interface AttachmentIdsResult {
  filename: string;
  row_count: number;
  id_column: string;
  rally_ids: string[];
}

export interface AttachmentRunRequest {
  jira: JiraConnection;
  rally: RallyConnection;
  rally_id_field: string;
  rally_ids: string[];
  dry_run: boolean;
}

export interface AttachmentItemResult {
  rally_id: string;
  jira_key: string;
  file_name: string;
  source: string;
  status: string;
  detail: string;
}

export interface AttachmentJob {
  job_id: string;
  state: string;
  dry_run: boolean;
  total_ids: number;
  processed_ids: number;
  resolved: number;
  unresolved: number;
  uploaded: number;
  exists: number;
  skipped: number;
  errors: number;
  progress: number;
  log: string[];
  items: AttachmentItemResult[];
  started_at: string;
  finished_at: string;
}

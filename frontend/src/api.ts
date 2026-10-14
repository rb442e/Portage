import type {
  CanonicalFieldDef, ConnectionTestResult, ExportResult, GeneratedCode, JiraConnection, JiraMetaResult,
  JobStatus, LegacyImportResult, LookupCsvPreview, LookupTable, MappingCatalog, MappingTemplate,
  PreviewResult, RallyConnection, SourcePreview, BatchUploadResult, BatchFileItem, ExportRecord, ExportPreview,
  MappingValidation, AttachmentIdsResult, AttachmentJob, AttachmentRunRequest, ParentMapResult, SplitResult,
  CopyDescriptionResult, CopyDescIdsResult, CopyDescJob, SavedConnectionState, LookupVersion, EntryDiff,
  SettingsView, SettingValue, McpConnection,
} from "./types";

const BASE = "/api";

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface MigrationRequest {
  source_id: string;
  jira: JiraConnection;
  rally?: RallyConnection | null;
  mapping_id?: number | null;
  mapping?: MappingTemplate | null;
  force_type?: string | null;
  lookup_ids: number[];
  type_map: Record<string, string>;
  include_attachments: boolean;
  dry_run: boolean;
  migration_id?: string | null;
  parent_map_id?: string | null;
  split_rows?: number;
}

export interface BatchMigrationRequest {
  files: BatchFileItem[];
  jira?: JiraConnection | null;
  mapping_id?: number | null;
  mapping?: MappingTemplate | null;
  lookup_ids: number[];
  type_map: Record<string, string>;
  include_attachments: boolean;
  migration_id?: string | null;
  parent_map_id?: string | null;
  split_rows?: number;
}

export interface CopyDescriptionRequest {
  jira: JiraConnection;
  rally: RallyConnection;
  rally_id: string;
  jira_key?: string;
}

export interface CopyDescBulkRequest {
  jira: JiraConnection;
  rally: RallyConnection;
  rally_id_field: string;
  rally_ids: string[];
  id_map?: Record<string, string>;
  dry_run: boolean;
  tables_only: boolean;
}

export const api = {
  health: () => req<{ status: string; version: string }>("/health"),

  testConnections: (jira?: JiraConnection, rally?: RallyConnection) =>
    req<ConnectionTestResult[]>("/connections/test", {
      method: "POST",
      body: JSON.stringify({ jira: jira || null, rally: rally || null }),
    }),

  discoverJira: (jira: JiraConnection) =>
    req<JiraMetaResult>("/connections/discover", {
      method: "POST",
      body: JSON.stringify({ jira }),
    }),

  saveConnections: (jira: JiraConnection, rally: RallyConnection) =>
    req<SavedConnectionState>("/connections/save", { method: "POST", body: JSON.stringify({ jira, rally }) }),
  savedConnections: () => req<SavedConnectionState>("/connections/saved"),
  forgetConnections: () => req<SavedConnectionState>("/connections/saved", { method: "DELETE" }),

  uploadSource: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/sources/upload`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<SourcePreview>;
  },

  uploadBatch: async (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const res = await fetch(`${BASE}/sources/upload-batch`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<BatchUploadResult>;
  },

  canonicalFields: () => req<string[]>("/mappings/canonical-fields"),
  fields: () => req<CanonicalFieldDef[]>("/mappings/fields"),
  dataTypes: () => req<string[]>("/mappings/data-types"),
  artifactTypes: () => req<string[]>("/mappings/artifact-types"),
  mappingCatalog: () => req<MappingCatalog>("/mappings/catalog"),
  generateCode: (tpl: MappingTemplate) =>
    req<GeneratedCode>("/mappings/generate", { method: "POST", body: JSON.stringify(tpl) }),
  defaultTemplate: () => req<MappingTemplate>("/mappings/defaults"),
  importLegacy: () => req<LegacyImportResult>("/mappings/import-legacy", { method: "POST" }),
  builtinTemplate: () => req<MappingTemplate>("/mappings/builtin"),
  listMappings: () => req<MappingTemplate[]>("/mappings"),
  saveMapping: (tpl: MappingTemplate) =>
    req<MappingTemplate>("/mappings", { method: "POST", body: JSON.stringify(tpl) }),
  deleteMapping: (id: number) => req<any>(`/mappings/${id}`, { method: "DELETE" }),

  lookupKinds: () => req<string[]>("/lookups/kinds"),
  listLookups: (kind?: string, side?: string) => {
    const q = new URLSearchParams();
    if (kind) q.set("kind", kind);
    if (side) q.set("side", side);
    const qs = q.toString();
    return req<LookupTable[]>(`/lookups${qs ? `?${qs}` : ""}`);
  },
  saveLookup: (lk: LookupTable) =>
    req<LookupTable>("/lookups", { method: "POST", body: JSON.stringify(lk) }),
  deleteLookup: (id: number) => req<any>(`/lookups/${id}`, { method: "DELETE" }),
  lookupVersions: (id: number) => req<LookupVersion[]>(`/lookups/${id}/versions`),
  lookupDiff: (id: number, fromVersion: number) => req<EntryDiff>(`/lookups/${id}/diff?from_version=${fromVersion}`),
  restoreLookup: (id: number, version: number) => req<LookupTable>(`/lookups/${id}/restore/${version}`, { method: "POST" }),
  parseLookupCsv: async (file: File, kind: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const res = await fetch(`${BASE}/lookups/parse`, { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.json() as Promise<LookupCsvPreview>;
  },
  extractLookup: async (file: File, source_col: string, target_col: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_col", source_col);
    form.append("target_col", target_col);
    const res = await fetch(`${BASE}/lookups/extract`, { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.json() as Promise<{ entries: Record<string, string> }>;
  },

  preview: (r: MigrationRequest) =>
    req<PreviewResult>("/migrations/preview", { method: "POST", body: JSON.stringify(r) }),
  export: (r: MigrationRequest) =>
    req<ExportResult>("/migrations/export", { method: "POST", body: JSON.stringify(r) }),
  previewBatch: (r: BatchMigrationRequest) =>
    req<PreviewResult>("/migrations/preview-batch", { method: "POST", body: JSON.stringify(r) }),
  exportBatch: (r: BatchMigrationRequest) =>
    req<ExportResult>("/migrations/export-batch", { method: "POST", body: JSON.stringify(r) }),
  validate: (r: MigrationRequest) =>
    req<MappingValidation>("/migrations/validate", { method: "POST", body: JSON.stringify(r) }),
  validateBatch: (r: BatchMigrationRequest) =>
    req<MappingValidation>("/migrations/validate-batch", { method: "POST", body: JSON.stringify(r) }),
  exportFileUrl: (id: string, name: string) =>
    `${BASE}/migrations/exports/${id}/${encodeURIComponent(name)}`,
  exportZipUrl: (id: string) => `${BASE}/migrations/exports/${id}.zip`,
  exportsList: () => req<ExportRecord[]>("/migrations/exports"),
  exportPreview: (id: string, file: string, limit = 200) =>
    req<ExportPreview>(`/migrations/exports/${id}/preview?file=${encodeURIComponent(file)}&limit=${limit}`),
  uploadParentMap: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/migrations/parent-map`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<ParentMapResult>;
  },
  run: (r: MigrationRequest) =>
    req<JobStatus>("/migrations/run", { method: "POST", body: JSON.stringify(r) }),
  job: (id: string) => req<JobStatus>(`/migrations/jobs/${id}`),
  jobs: () => req<JobStatus[]>("/migrations/jobs"),

  uploadAttachmentIds: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/attachments/upload-ids`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<AttachmentIdsResult>;
  },
  runAttachments: (r: AttachmentRunRequest) =>
    req<AttachmentJob>("/attachments/run", { method: "POST", body: JSON.stringify(r) }),
  attachmentJob: (id: string) => req<AttachmentJob>(`/attachments/jobs/${id}`),
  attachmentReportUrl: (id: string) => `${BASE}/attachments/jobs/${id}/report.csv`,

  splitFile: async (file: File, maxRows: number, hasHeader: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("max_rows", String(maxRows));
    form.append("has_header", String(hasHeader));
    const res = await fetch(`${BASE}/tools/split`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<SplitResult>;
  },
  splitZipUrl: (id: string) => `${BASE}/tools/splits/${id}.zip`,
  splitFileUrl: (id: string, name: string) =>
    `${BASE}/tools/splits/${id}/${encodeURIComponent(name)}`,

  copyDescriptionPreview: (r: CopyDescriptionRequest) =>
    req<CopyDescriptionResult>("/tools/copy-description/preview", { method: "POST", body: JSON.stringify(r) }),
  copyDescriptionApply: (r: CopyDescriptionRequest) =>
    req<CopyDescriptionResult>("/tools/copy-description/apply", { method: "POST", body: JSON.stringify(r) }),

  uploadCopyDescIds: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/tools/copy-description/upload-ids`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<CopyDescIdsResult>;
  },
  copyDescBulk: (r: CopyDescBulkRequest) =>
    req<CopyDescJob>("/tools/copy-description/bulk", { method: "POST", body: JSON.stringify(r) }),
  copyDescJob: (id: string) => req<CopyDescJob>(`/tools/copy-description/jobs/${id}`),
  copyDescReportUrl: (id: string) => `${BASE}/tools/copy-description/jobs/${id}/report.csv`,
  settings: () => req<SettingsView>("/settings"),
  saveSettings: (section: string, values: Record<string, SettingValue>) =>
    req<SettingsView>(`/settings/${section}`, { method: "PUT", body: JSON.stringify({ values }) }),
  resetSetting: (section: string, key?: string) =>
    req<SettingsView>(key ? `/settings/${section}/${key}` : `/settings/${section}`, { method: "DELETE" }),
  mcpConnection: () => req<McpConnection>("/settings/mcp/connection"),
};

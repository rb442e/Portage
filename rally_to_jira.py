#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
import pandas as pd
import yaml
import sys
from typing import Dict, List, Optional, Tuple

DEFAULT_STATUS_MAP = {"Defined":"To Do","Prepare":"Ready","In-Progress":"In Progress","Completed":"In Review","Done":"Accepted"}
DEFAULT_PRIORITY_MAP = {"Crash / Blocker":"Highest","Blocker":"Highest","Critical":"Highest","Major":"High","High":"High","Normal":"Medium","Medium":"Medium","Minor":"Low","Low":"Low","Trivial":"Lowest"}
JIRA_BASE_COLUMNS = ["Issue Id","Parent Id","Project Key","Project","Issue Type","Summary","Description","Reporter","Assignee","Status","Priority","Labels","Fix Version/s","Affects Version/s","Components","Sprint","Epic ID","Epic Name","Feature ID","Feature Name","Story Points","Original Estimate","Created","Start Date","Due Date","Issue Links","Team","Milestones","Rally ID","Comments","Attachment 1","Attachment 2","Attachment 3","Attachment 4","Attachment 5","Comment 1","Comment 2","Comment 3","Comment 4","Comment 5","Severity","Environment","RCA","Root Cause","State","Schedule State","ITPR","Parent","Link"]

# RB: Columns removed ONLY from the task-specific import files (per-type
# jira_<task>.csv and the per-train jira_task_*.csv splits). All other issue
# types and the consolidated jira_all_issues.csv are unaffected.
TASK_EXCLUDE_COLUMNS = ["Priority","Labels","Fix Version/s","Affects Version/s","Components","Sprint","Epic ID","Epic Name","Feature ID","Feature Name","Story Points","Original Estimate","Created","Start Date","Due Date","Issue Links","Comments","Attachment 1","Attachment 2","Attachment 3","Attachment 4","Attachment 5","Comment 1","Comment 2","Comment 3","Comment 4","Comment 5","Severity","Environment","RCA","Root Cause","Schedule State","ITPR"]
TASK_COLUMNS = [c for c in JIRA_BASE_COLUMNS if c not in TASK_EXCLUDE_COLUMNS]

def read_csv_if_exists(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try: return pd.read_csv(path, encoding="utf-8-sig")
        except Exception: return pd.read_csv(path, encoding="utf-8-sig", engine="python")
    return None
def get_col(r: pd.Series, key: str, default=""):
    v = r.get(key, default); 
    return default if pd.isna(v) else v
def ensure_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns: df[c] = ""
    return df
# RB: Rally feature/story descriptions embed section headings inline (e.g.
# "Business Value: ... In Scope ... Out of Scope: ... Dependencies ...").
# format_description() detects the headings that are ALREADY present, puts each on
# its own line, keeps their original names/order, de-duplicates repeated headings,
# and adds nothing new. Headings are only recognized when they start the text, are
# preceded by the template's non-breaking space, or are immediately followed by a
# colon, so words appearing in prose (or in file names) are not misread as headings.
DESC_LABELS = [
    (r"Participants", "participants"),
    (r"Problem Statement(?:\s*\([^)]*\))?", "problem_statement"),
    (r"Business Value", "business_value"),
    (r"Business Outcome Hypothesis", "business_outcome_hypothesis"),
    (r"Benefit Hypothesis", "benefit_hypothesis"),
    (r"Hypothesis Statement", "hypothesis_statement"),
    (r"Contacts\s*/\s*Dependencies", "contacts_dependencies"),
    (r"Out of Scope", "out_of_scope"),
    (r"In[\-\s]?Scope", "in_scope"),
    (r"Non[\-\s]*function\w*\s*requirements?", "non_functional"),
    (r"Success Criteria and Metrics", "success_criteria"),
    (r"Success Criteria", "success_criteria"),
    (r"Data Topics", "data_topics"),
    (r"Data flow", "data_flow"),
    (r"Architectural impacts?(?:\s*\[[^\]]*\])?", "arch_impacts"),
    (r"UX/UI Content(?:\s*\[[^\]]*\])?", "ux_ui"),
    (r"Accessibility", "accessibility"),
    (r"Contacts\s*/\s*Dependenc(?:ies|y)", "contacts_dependencies"),
    (r"Dependenc(?:ies|y)", "dependencies"),
    (r"Outstanding Questions", "questions"),
    (r"Open Questions", "questions"),
    (r"Sample Use Cases", "use_cases"),
    (r"Use Cases", "use_cases"),
    (r"Integration Testing Required", "integration_testing"),
    (r"Integration Testing", "integration_testing"),
    (r"API,?\s?Endpoints,?\s?URL'?s?", "api_endpoints"),
    (r"Acceptance Criteria", "acceptance_criteria"),
    (r"Assumptions?", "assumptions"),
    (r"Notes", "notes"),
    (r"Objective", "overview"),
    (r"Overview", "overview"),
    (r"Background", "overview"),
]
# RB: User-story-only heading set. Applied exclusively to User Story descriptions
# (features use DESC_LABELS). Same detection/formatting behavior as features:
# each heading already present in the text is put on its own line, in original
# order, de-duplicated, nothing added. The story opener ("As a <role>, I want ...
# so that ...") is kept intact as the leading paragraph via the preamble handling.
STORY_DESC_LABELS = [
    (r"Description of Need", "description_of_need"),
    (r"DESCRIPTION", "description"),
    (r"Problem Statement(?:\s*\([^)]*\))?", "problem_statement"),
    (r"Benefit Hypothesis", "benefit_hypothesis"),
    (r"Business Context", "business_context"),
    (r"Business Value", "business_value"),
    (r"Object List", "object_list"),
    (r"High[\-\s]?Level Data Flow", "hl_data_flow"),
    (r"Data Flow", "data_flow"),
    (r"Additional Requirements\s*/?\s*(?:and\s*)?Activities", "additional_requirements"),
    (r"Additional Requirements", "additional_requirements"),
    (r"Additional Comments", "additional_comments"),
    (r"Non[\-\s]*function\w*\s*requirements?", "non_functional"),
    (r"Acceptance Criteria", "acceptance_criteria"),
    (r"Definition of Done", "definition_of_done"),
    (r"Out of Scope", "out_of_scope"),
    (r"In[\-\s]?Scope", "in_scope"),
    (r"Contacts\s*/\s*Dependenc(?:ies|y)", "contacts_dependencies"),
    (r"Dependenc(?:ies|y)", "dependencies"),
    (r"Outstanding Questions", "questions"),
    (r"Open Questions", "questions"),
    (r"Assumptions?", "assumptions"),
    (r"Target Deploy Date", "target_deploy_date"),
    (r"Name of new pool", "name_of_new_pool"),
    (r"Priority", "priority"),
    (r"Notes", "notes"),
    (r"Links", "links"),
]

# RB: Defect-only heading set for description normalization.
DEFECT_DESC_LABELS = [
    (r"Steps\s*To\s*Reproduce", "steps_to_reproduce"),
    (r"Expected\s*Result", "expected_result"),
    (r"Impact", "impact"),
    (r"Actual\s*Result", "actual_result"),
    (r"Issue\s*Description", "issue_description"),
    (r"Description\s*of\s*Issue", "description_of_issue"),
    (r"Issue", "issue"),
    (r"Sample\s*Error", "sample_error"),
    (r"Error", "error"),
    (r"Exception", "exception"),
    (r"Steps", "steps"),
    (r"Context", "context"),
    (r"TEST\s*USER\s*\(\s*QA\s*or\s*PROD\s*\)", "test_user"),
    (r"INSTRUCTION\s*-\s*ISSUE\s*SUMMARY", "instruction_issue_summary"),
    (r"Workaround", "workaround"),
    (r"Defect\s*Details", "defect_details"),
    (r"Instruction", "instruction"),
    (r"INcidents\s*reported", "incidents_reported"),
]

def _desc_pattern(labels):
    return re.compile(r"(" + "|".join(p for p, _ in labels) + r")[ \t\u00a0]*(:?)[ \t\u00a0]*", re.IGNORECASE)

def _desc_key(label_text: str, labels) -> str:
    lt = label_text.strip()
    for pat, key in labels:
        if re.fullmatch(pat, lt, re.IGNORECASE):
            return key
    return "other"

def _desc_clean(t: str) -> str:
    t = (t.replace("\u00a0", " ").replace("\u200b", "")
          .replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
          .replace("\u2192", "->").replace("\u2019", "'"))
    return re.sub(r"\s+", " ", t).strip()

def format_description(desc: str, labels=DESC_LABELS, generic: bool = False, force_known: bool = False) -> str:
    raw = desc or ""
    if not raw.strip():
        return raw
    # Safeguard: some exports carry markdown emphasis around headings (e.g.
    # "**Business Value:**", "### Digital:"). Strip stray '*' and heading '#'
    # markers so headings are detected cleanly and no stars leak into output.
    raw = re.sub(r"\*+", "", raw)
    raw = re.sub(r"#{2,}", "", raw)

    # marks: (start, end_after_label_colon, display_label, key, is_generic)
    marks = []

    # 1) Known headings.
    if force_known:
        # Defect-mode: split on configured labels even when ':' is absent.
        for pat_text, key in labels:
            forced_pat = re.compile(
                r"(?<!\w)(" + pat_text + r")(?!\w)[ \t\u00a0]*(?:[:;])?[ \t\u00a0]*",
                re.IGNORECASE,
            )
            for m in forced_pat.finditer(raw):
                label = m.group(1).strip().rstrip(":").strip()
                marks.append((m.start(), m.end(), label, key, False))
    else:
        # Standard mode for features/stories.
        pat = _desc_pattern(labels)
        for m in pat.finditer(raw):
            i = m.start()
            prev = raw[i-1] if i > 0 else ""
            is_head = (i == 0) or prev in ("\u00a0", "\n", "\r") or m.group(2) == ":"
            if not is_head:
                continue
            label = m.group(1).strip().rstrip(":").strip()
            marks.append((m.start(), m.end(), label, _desc_key(m.group(1), labels), False))

    # 2) Generic "<label>:" headings (stories). Any phrase immediately before a colon
    #    at a STRONG boundary (start / nbsp / newline / tab / period / colon / semicolon)
    #    becomes its own line. Guards skip URLs (http://...) and clock/ratio values
    #    (e.g. 9:00, 3:1). Strong boundaries (not plain spaces) prevent absorbing a
    #    preceding value into the next heading in run-on text.
    if generic:
        for cm in re.finditer(r":", raw):
            ci = cm.start()
            after = raw[ci+1:ci+2]
            if after == "/" or after.isdigit():
                continue
            k = ci - 1
            start = 0
            while k >= 0:
                if raw[k] in ("\u00a0", "\n", "\r", "\t", ".", ":", ";"):
                    start = k + 1
                    break
                k -= 1
            label = raw[start:ci].strip()
            if (not label) or len(label) > 60 or not re.search(r"[A-Za-z]", label):
                continue
            if label.lower() in ("http", "https", "ftp"):
                continue
            marks.append((start, ci + 1, label, "gen:" + label.lower(), True))

    if not marks:
        return _desc_clean(raw)

    # Position order; prefer known headings over generic splits at same index.
    marks.sort(key=lambda x: (x[0], 1 if x[4] else 0, -(x[1] - x[0])))

    filtered = []
    seen_keys = set()
    skip_spans = []
    last_end = -1
    for s, e, label, key, is_gen in marks:
        if s < last_end:
            continue
        # De-duplicate repeated KNOWN headings only in non-generic mode (features);
        # blank the repeated bare label so it doesn't linger in the content.
        if (not is_gen) and (not generic) and key in seen_keys:
            skip_spans.append((s, e))
            continue
        if not is_gen:
            seen_keys.add(key)
        filtered.append((s, e, label))
        last_end = e

    raw2 = raw
    if skip_spans:
        chars = list(raw)
        for s, e in skip_spans:
            for j in range(s, e):
                chars[j] = " "
        raw2 = "".join(chars)

    parts = []
    pre = _desc_clean(raw2[:filtered[0][0]])
    if pre:
        parts.append(pre)
    for idx, (s, e, label) in enumerate(filtered):
        end = filtered[idx+1][0] if idx+1 < len(filtered) else len(raw2)
        content = _desc_clean(raw2[e:end])
        parts.append(f"{label}:\n{content}" if content else f"{label}:")
    return "\n\n".join(parts).strip()

# Private, never-typed control char used to carry multiple mapped values (e.g.
# milestones/versions) in a single cell. Chosen because version names can contain
# spaces, commas and colons (e.g. "MI18247: 26.06.1 Q2 Major Release"), so those
# characters are unsafe as delimiters. expand_repeated_column() splits on this and
# emits repeated same-named columns, the only shape Jira's CSV importer accepts for
# multi-value fields like Fix Version/s.
MULTI_VALUE_SEP = "\u0001"
def expand_repeated_column(df: pd.DataFrame, col: str, sep: str = MULTI_VALUE_SEP) -> pd.DataFrame:
    if col not in df.columns:
        return df
    def _split(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return []
        return [p for p in str(v).split(sep) if p != ""]
    lists = df[col].apply(_split)
    max_n = max((len(x) for x in lists), default=0)
    # No row has more than one value: keep a single, clean column.
    if max_n <= 1:
        out = df.copy()
        out[col] = lists.apply(lambda x: x[0] if x else "")
        return out
    # Rebuild the frame, replacing `col` with `max_n` identically-named columns
    # (pandas allows duplicate labels; Jira reads each as a separate value).
    series_list: List[pd.Series] = []
    headers: List[str] = []
    for c in df.columns:
        if c == col:
            for i in range(max_n):
                headers.append(col)
                series_list.append(lists.apply(lambda x, i=i: x[i] if i < len(x) else "").reset_index(drop=True))
        else:
            headers.append(c)
            series_list.append(df[c].reset_index(drop=True))
    out = pd.concat(series_list, axis=1)
    out.columns = headers
    return out
def normalize_labels(tag_str: str) -> str:
    if pd.isna(tag_str) or str(tag_str).strip() == "": return ""
    items = [x.strip().replace(" ", "-") for x in re.split(r"[;,]", str(tag_str)) if x.strip() != ""]
    return " ".join(sorted(set(items)))
def safe_file_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower()).strip("_")
    return token if token else "unassigned"
def normalize_name_key(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower())
    return " ".join(cleaned.split())
def name_variants(value: str) -> List[str]:
    raw = str(value).strip()
    normalized = normalize_name_key(raw)
    if not normalized:
        return []
    variants = [normalized]
    if "," in raw:
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) >= 2:
            reordered = normalize_name_key(" ".join(parts[1:] + parts[:1]))
            if reordered and reordered not in variants:
                variants.append(reordered)
    else:
        parts = normalized.split()
        if len(parts) >= 2:
            reversed_name = normalize_name_key(" ".join([parts[-1]] + parts[:-1]))
            if reversed_name and reversed_name not in variants:
                variants.append(reversed_name)
    return variants
def split_parent_reference(value: str) -> Tuple[str, str]:
    raw = str(value).strip()
    if not raw:
        return "", ""
    left, right = (raw.split(":", 1) + [""])[:2]
    ref_id = re.sub(r"^(Epic|Feature)\s+", "", left.strip(), flags=re.IGNORECASE)
    ref_name = right.strip()
    return ref_id, ref_name
def make_issue_id(prefix: str, formatted_id: str) -> str:
    return f"{prefix}-{formatted_id}" if formatted_id and str(formatted_id).strip() else f"{prefix}-GEN-0"
def format_estimate_hours(val) -> str:
    # Rally Refined Estimate is decimal hours; Jira Original Estimate expects seconds.
    if val is None or (isinstance(val, float) and pd.isna(val)): return ""
    s = str(val).strip()
    if not s: return ""
    try:
        hours = float(s)
    except ValueError:
        return s
    if hours <= 0: return ""
    return str(int(round(hours * 3600)))
def format_date(created_raw: str) -> Optional[str]:
    if not created_raw: return None
    # Some Rally exports (e.g. epics) use underscores instead of spaces inside
    # values (e.g. "2026-07-01_11:59_PM_MDT"). Dates never legitimately contain
    # underscores, so normalize them to spaces before parsing.
    clean = re.sub(r'_+', ' ', str(created_raw)).strip()
    clean = re.sub(r'\s+(EDT|EST|PST|CST|MST|MDT)$', '', clean).strip()
    for fmt in ["%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"]:
        try: return pd.to_datetime(clean, format=fmt, errors='raise').strftime("%m/%d/%y %H:%M")
        except (ValueError, TypeError): continue
    dt = pd.to_datetime(clean, errors='coerce')
    return dt.strftime("%m/%d/%y %H:%M") if pd.notna(dt) else None
class Converter:
    def __init__(self, cfg: Dict, in_dir: Path, out_dir: Path):
        self.cfg, self.in_dir, self.out_dir = cfg, in_dir, out_dir
        self.base_dir = Path(__file__).resolve().parent
        self.mappings_dir = self.base_dir / "mappings"
        self.status_map = cfg.get("status_map", DEFAULT_STATUS_MAP)
        self.priority_map = cfg.get("priority_map", DEFAULT_PRIORITY_MAP)
        self.project_key = cfg["project_key"]
        self.components_map = cfg.get("components_map", {})
        self.use_roadmaps = cfg.get("use_roadmaps_levels", False)
        self.test_mode = cfg.get("test_mode", "custom")
        self.story_points_field = cfg.get("rally_story_points_field", "PlanEstimate")
        self.refined_estimate_field = cfg.get("rally_refined_estimate_field", "Refined Estimate")
        self.sprint_map = {str(k): str(v) for k, v in cfg.get("sprint_map", {}).items()}
        self.team_map = {str(k): str(v) for k, v in cfg.get("team_map", {}).items()}
        self.version_map = {str(k): str(v) for k, v in cfg.get("version_map", {}).items()}
        self.user_map = {str(k).lower(): str(v) for k, v in cfg.get("user_map", {}).items()}
        self.fn = {"epics": cfg.get("files", {}).get("epics", "epics.csv"),"features": cfg.get("files", {}).get("features", "features.csv"),"stories": cfg.get("files", {}).get("userstories", "userstories.csv"),"tasks": cfg.get("files", {}).get("tasks", "tasks.csv"),"defects": cfg.get("files", {}).get("defects", "defects.csv"),"testcases": cfg.get("files", {}).get("testcases", "testcases.csv"),"testsets": cfg.get("files", {}).get("testsets", "testsets.csv"),"releases": cfg.get("files", {}).get("releases", "releases.csv"),"iterations": cfg.get("files", {}).get("iterations", "iterations.csv"),"attachments": cfg.get("files", {}).get("attachments", "attachments.csv"),"comments": cfg.get("files", {}).get("comments", "comments.csv"),"timeentries": cfg.get("files", {}).get("timeentries", "timeentries.csv")}
        self.inputs = {k: read_csv_if_exists(in_dir / v) for k, v in self.fn.items()}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.project_to_train = self._load_project_to_train_map()
        self.project_to_board = self._load_project_to_board_map()
        self.train_sprint_maps = self._load_train_sprint_maps()
        self.train_version_maps = self._load_train_version_maps()
        self.project_to_atlassian_team_id = self._load_project_to_team_id_map()
        self.feature_to_jira_id = self._load_feature_to_jira_id_map()
        self.user_lookup = self._load_user_map()
        self.attach_map = self._build_attachment_map()
        self.comment_map = self._build_comment_map()
    def _load_project_to_train_map(self) -> Dict[str, str]:
        path = self.mappings_dir / "mapping_train_to_project.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        mapping = {}
        for _, r in df.iterrows():
            project = normalize_name_key(get_col(r, "Project", ""))
            train = str(get_col(r, "Train", "")).strip()
            if project and train:
                mapping[project] = train
        return mapping
    def _load_project_to_board_map(self) -> Dict[str, str]:
        path = self.mappings_dir / "project_to_board.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        mapping = {}
        for _, r in df.iterrows():
            project = normalize_name_key(get_col(r, "Project", ""))
            board = normalize_name_key(get_col(r, "Board", ""))
            if project and board:
                mapping[project] = board
        return mapping
    def _load_user_map(self) -> Dict[str, str]:
        path = self.mappings_dir / "user_mapping.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        lookup = {}
        for _, r in df.iterrows():
            email = str(get_col(r, "Email", "")).strip()
            if not email:
                continue
            for variant in name_variants(get_col(r, "Name", "")):
                lookup.setdefault(variant, email)
        return lookup
    def _load_train_sprint_maps(self) -> Dict[str, List[Dict[str, str]]]:
        maps: Dict[str, List[Dict[str, str]]] = {}
        for path in self.mappings_dir.glob("*_train_sprint_mapping.csv"):
            df = read_csv_if_exists(path)
            if df is None:
                continue
            train_key = normalize_name_key(path.stem.replace("_sprint_mapping", "").replace("_", " "))
            rows: List[Dict[str, str]] = []
            for _, r in df.iterrows():
                sprint_name = str(get_col(r, "Sprint Name", "")).strip()
                sprint_id = re.sub(r"\.0$", "", str(get_col(r, "Sprint ID", "")).strip())
                board_name = str(get_col(r, "Board Name", "")).strip()
                if not sprint_name or not sprint_id:
                    continue
                rows.append({
                    "board": board_name,
                    "board_norm": normalize_name_key(board_name),
                    "sprint": sprint_name,
                    "sprint_norm": normalize_name_key(sprint_name),
                    "sprint_id": sprint_id,
                })
            if rows:
                maps[train_key] = rows
        return maps
    def _load_train_version_maps(self) -> Dict[str, Dict[str, str]]:
        path = self.mappings_dir / "train_version_mapping.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        maps: Dict[str, Dict[str, str]] = {}
        for _, r in df.iterrows():
            train_key = normalize_name_key(get_col(r, "Train", ""))
            milestone_id = re.sub(r"\.0$", "", str(get_col(r, "Milestone ID", "")).strip())
            version_name = str(get_col(r, "Version Name", "")).strip()
            if not train_key or not milestone_id or not version_name:
                continue
            maps.setdefault(train_key, {})[milestone_id] = version_name
        return maps
    def _load_project_to_team_id_map(self) -> Dict[str, str]:
        path = self.mappings_dir / "team_id_mapping.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        mapping = {}
        for _, r in df.iterrows():
            team_name = normalize_name_key(get_col(r, "Team Name", ""))
            team_id = str(get_col(r, "Atlassian Team ID", "")).strip()
            if team_name and team_id:
                mapping[team_name] = team_id
        return mapping
    def _load_feature_to_jira_id_map(self) -> Dict[str, str]:
        # RB: Rally Feature Formatted ID (e.g. "F231056") -> Jira numeric Issue ID.
        # Sourced from mappings/feature_to_jira_id.csv (post-import Jira export).
        # Used to set the User Story "Parent Id" to its parent Feature's Jira ID.
        path = self.mappings_dir / "feature_to_jira_id.csv"
        df = read_csv_if_exists(path)
        if df is None:
            return {}
        mapping = {}
        for _, r in df.iterrows():
            fid = str(get_col(r, "Feature ID", "")).strip()
            jira_id = re.sub(r"\.0$", "", str(get_col(r, "Jira ID", "")).strip())
            if fid and jira_id:
                mapping[fid] = jira_id
        return mapping
    def _lookup_email_in_map(self, raw_name: str, lookup: Dict[str, str]) -> str:
        for variant in name_variants(raw_name):
            if variant in lookup:
                return lookup[variant]
        raw_parts = normalize_name_key(raw_name).split()
        if len(raw_parts) >= 2:
            raw_first = raw_parts[0]
            raw_last = raw_parts[-1]
            for mapped_name, email in lookup.items():
                mapped_parts = mapped_name.split()
                if len(mapped_parts) < 2:
                    continue
                mapped_first = mapped_parts[0]
                mapped_last = mapped_parts[-1]
                if mapped_last == raw_last and (mapped_first.startswith(raw_first) or raw_first.startswith(mapped_first)):
                    return email
        return ""
    def _build_attachment_map(self):
        df = self.inputs.get("attachments"); m = {}
        if df is not None:
            for _, r in df.iterrows():
                art = str(get_col(r, "ArtifactFormattedID", "")).strip()
                url = str(get_col(r, "FileURL", "")).strip()
                if art: m.setdefault(art, []).append(url)
        return m
    def _build_comment_map(self):
        df = self.inputs.get("comments"); m = {}
        if df is not None:
            for _, r in df.iterrows():
                art = str(get_col(r, "ArtifactFormattedID", "")).strip()
                text = str(get_col(r, "Text", "")).strip()
                if art and text: m.setdefault(art, []).append(text)
        return m
    def _project_to_train(self, project_name: str) -> str:
        project_key = normalize_name_key(project_name)
        return self.project_to_train.get(project_key, str(project_name).strip())
    def _resolve_train_sprint_rows(self, train_name: str) -> List[Dict[str, str]]:
        train_norm = normalize_name_key(train_name)
        if train_norm in self.train_sprint_maps:
            return self.train_sprint_maps[train_norm]
        for key, rows in self.train_sprint_maps.items():
            if key in train_norm or train_norm in key:
                return rows
        return []
    def _map_user(self, email_or_name: str, train_name: str = "") -> str:
        if not email_or_name: return ""
        raw = str(email_or_name).strip()
        if "@" in raw:
            return raw
        mapped_email = self._lookup_email_in_map(raw, self.user_lookup)
        if mapped_email:
            return mapped_email
        return self.user_map.get(raw.lower(), raw)
    def _map_status(self, schedule_state: str) -> str:
        return "" if not schedule_state else self.status_map.get(str(schedule_state), str(schedule_state))
    def _map_priority(self, sev_or_pri: str) -> str:
        return "" if not sev_or_pri else self.priority_map.get(str(sev_or_pri), str(sev_or_pri))
    def _map_labels(self, tags_str: str) -> str:
        return normalize_labels(tags_str)
    def _map_sprint(self, iteration_name: str, project_name: str) -> str:
        if iteration_name is None or (isinstance(iteration_name, float) and pd.isna(iteration_name)):
            return ""
        s = str(iteration_name).strip()
        if not s:
            return ""

        train_name = self._project_to_train(project_name)
        rows = self._resolve_train_sprint_rows(train_name)
        if rows:
            sprint_norm = normalize_name_key(s)
            project_norm = normalize_name_key(project_name)
            candidates = [r for r in rows if r["sprint_norm"] == sprint_norm]
            if candidates:
                mapped_board = self.project_to_board.get(project_norm)
                if mapped_board:
                    board_exact = [r for r in candidates if r["board_norm"] == mapped_board]
                    if board_exact:
                        return board_exact[0]["sprint_id"]
                    board_partial = [
                        r for r in candidates
                        if mapped_board in r["board_norm"] or r["board_norm"] in mapped_board
                    ]
                    if board_partial:
                        return board_partial[0]["sprint_id"]
                exact_board = [r for r in candidates if r["board_norm"] == project_norm]
                if exact_board:
                    return exact_board[0]["sprint_id"]
                partial_board = [
                    r for r in candidates
                    if project_norm in r["board_norm"] or r["board_norm"] in project_norm
                ]
                if partial_board:
                    return partial_board[0]["sprint_id"]
                unique_ids = sorted({r["sprint_id"] for r in candidates})
                if len(unique_ids) == 1:
                    return unique_ids[0]

        # Fall back to the original Rally value when no mapping is found.
        try:
            n = float(s)
            if n.is_integer():
                return str(int(n))
        except ValueError:
            pass
        return s
    def _map_version(self, release_name: str) -> str:
        return "" if not release_name else self.version_map.get(str(release_name), str(release_name))
    def _map_milestone(self, milestone_id: str, project_name: str) -> str:
        if not milestone_id:
            return ""
        train_norm = normalize_name_key(self._project_to_train(project_name))
        rows = self.train_version_maps.get(train_norm)
        if rows is None:
            for key, value in self.train_version_maps.items():
                if key in train_norm or train_norm in key:
                    rows = value
                    break
        # Accommodate multiple milestone IDs (e.g., "43345; 42217") separated by
        # semicolons, commas, or newlines; map each and join with the private
        # separator so they are later emitted as repeated "Milestones" columns
        # (Jira treats each as a separate Fix Version/s value on import).
        raw_ids = [re.sub(r"\.0$", "", p.strip()) for p in re.split(r"[;,\n]", str(milestone_id)) if p.strip()]
        if not raw_ids:
            return ""
        mapped = [(rows.get(mid, mid) if rows else mid) for mid in raw_ids]
        # De-duplicate while preserving order.
        seen = set()
        unique = [m for m in mapped if not (m in seen or seen.add(m))]
        return MULTI_VALUE_SEP.join(unique)
    def _map_team(self, team_name: str) -> str:
        return "" if not team_name else self.team_map.get(str(team_name), str(team_name))
    def _map_story_team_from_project(self, project_name: str) -> str:
        if not project_name:
            return ""
        return self.project_to_atlassian_team_id.get(normalize_name_key(project_name), "")
    def _gather_common(self, r: pd.Series, artifact_type: str, issue_type: str, formatted_id_col: str = "Formatted ID", format_desc: bool = False, desc_labels=None, generic_desc: bool = False, force_desc_labels: bool = False):
        fid = str(get_col(r, formatted_id_col, "")).strip()
        issue_id = make_issue_id(issue_type.upper(), fid)
        project_name = str(get_col(r, "Project", "")).strip()
        # RB: Resolve the train via the (case-insensitive) project->train map for all
        # artifact types, including Features. Previously Features used the raw project
        # name, so team-level projects (e.g. "Voltron") were never grouped under their
        # train (PLSST) and produced stray per-project output files.
        train_name = self._project_to_train(project_name)
        #desc = str(get_col(r, "Description", "") or get_col(r, "Notes", "")).strip()
        # RB: Reformat embedded section headings for selected artifact types only
        # (format_desc=True). Features use DESC_LABELS; User Stories pass their own
        # STORY_DESC_LABELS via desc_labels. All other artifact types keep their raw
        # description text unchanged.
        description_text = str(get_col(r, "Description", "")).strip()
        if format_desc:
            description_text = format_description(
                description_text,
                desc_labels or DESC_LABELS,
                generic=generic_desc,
                force_known=force_desc_labels,
            )
        notes_text = str(get_col(r, "Notes", "")).strip()
        if notes_text:
            desc = f"{description_text}\n\n----\n*Notes*\n\n{notes_text}"
        else:
            desc = description_text
        #print(f"desc: {desc}")
        reporter = self._map_user(get_col(r, "Submitted By", get_col(r, "Created By", get_col(r, "Creator", ""))), train_name)
        assignee = self._map_user(get_col(r, "Owner", get_col(r, "Owner Email", "")), train_name)
        schedule_state = get_col(r, "ScheduleState", get_col(r, "State", ""))
        #RB: change it based on data
        #schedule_state = get_col(r, "State", get_col(r, "Schedule State", ""))
        schedule_state = get_col(r, "State", get_col(r, "Schedule State", ""))
        rally_state = str(get_col(r, "State", get_col(r, "Schedule State", ""))).strip()
        status = self._map_status(schedule_state)
        priority = self._map_priority(get_col(r, "Severity", get_col(r, "Priority", "")))
        tags = self._map_labels(get_col(r, "Tags", ""))
        project_key = self.project_key
        components = self.components_map.get(artifact_type, "")
        sprint = self._map_sprint(
            get_col(r, "Iteration name", get_col(r, "Iteration Name", get_col(r, "Iteration", ""))),
            project_name,
        )
        # RB: Pass the Rally team column value through as-is (no team_id_mapping lookup).
        team = str(get_col(r, "Team", get_col(r, "Contributing Teams", ""))).strip()
        # team = self._map_team(get_col(r, "Contributing Teams", ""))
        # if artifact_type == "User Story":
        #     team = self._map_story_team_from_project(project_name)
        # elif artifact_type == "Feature":
        #     project_team = self._map_story_team_from_project(project_name)
        #     if project_team:
        #         team = project_team
        print(f"team: {team}")

        #RB: add column for Release version, milestone, etc.
        fix_version = ""
        print(f"fix_version: {fix_version}")
        milestone = get_col(r, "Milestones", get_col(r, "Milestones/Release ID", ""))
        milestone = self._map_milestone(str(milestone), project_name)
        print(f"milestone: {milestone.replace(MULTI_VALUE_SEP, ' | ')}")

        #fix_version = self._map_version(get_col(r, "Release", get_col(r, "Release Name", "")))
        affects_version = ""
        #created = str(get_col(r, "Creation Date", get_col(r, "Created", "")))[:10]
        #RB: created -> Creation Date

        created_raw = get_col(r, "Creation Date", get_col(r, "Created", ""))
        created = format_date(created_raw)
        # RB: Release column holds a date; if blank leave empty, else format to
        # MM/DD/YY HH:MM and map it to the Jira "Start Date" field.
        release_raw = str(get_col(r, "Release", "")).strip()
        start_date = (format_date(release_raw) or "") if release_raw else ""
        #RB: due -> Planned End Date
        due = format_date(get_col(r, "Planned End Date", ""))

        original_estimate = format_estimate_hours(get_col(r, self.refined_estimate_field, ""))
        if artifact_type == "Feature":
            story_points = get_col(r, self.refined_estimate_field, "")
        elif artifact_type == "User Story":
            story_points = get_col(r, self.story_points_field, "")
        else:
            story_points = get_col(r, self.story_points_field, "")

        fid_key = fid if fid else get_col(r, "ObjectID", "")
        attachments = self.attach_map.get(fid_key, [])
        comments = self.comment_map.get(fid_key, [])
        base = {c: "" for c in JIRA_BASE_COLUMNS}
        base.update({"Issue Id": issue_id,"Project Key": project_key,"Project": project_name,"Issue Type": issue_type,"Summary": str(get_col(r, "Name", get_col(r, "Title", ""))),"Description": desc,"Reporter": reporter,"Assignee": assignee,"Status": status,"Priority": priority,"Labels": tags,"Fix Version/s": fix_version,"Affects Version/s": affects_version,"Components": components,"Sprint": sprint,"Epic Name": "","Story Points": story_points,"Original Estimate": original_estimate,"Created": created,"Start Date": start_date,"Due Date": due,"Issue Links": "", "Team": team, "Milestones": milestone, "Rally ID": "", "State": rally_state})
        for i in range(5):
            base[f"Attachment {i+1}"] = attachments[i] if i < len(attachments) else ""
            base[f"Comment {i+1}"] = comments[i] if i < len(comments) else ""
        return base, str(fid), train_name
    def _write_split_files(self, rows_by_key: Dict[str, List[Dict]], filename_prefix: str, columns: Optional[List[str]] = None) -> None:
        # RB: Shared per-group CSV writer used by the feature (by project), story
        # (by train) and bug (by train) splits so the three paths stay identical.
        # Emits <filename_prefix>_<safe token>.csv for each group.
        # RB: Optional 'columns' restricts the output to a specific column subset
        # (used only by the task split to drop task-excluded columns); defaults to
        # JIRA_BASE_COLUMNS so feature/story/bug splits are unaffected.
        out_columns = columns if columns is not None else JIRA_BASE_COLUMNS
        for key, rows in rows_by_key.items():
            df = pd.DataFrame(rows); df = ensure_cols(df, JIRA_BASE_COLUMNS); df = df[out_columns]
            df = expand_repeated_column(df, "Milestones")
            suffix = safe_file_token(key)
            (self.out_dir / f"{filename_prefix}_{suffix}.csv").write_text(df.to_csv(index=False), encoding="utf-8-sig")
    def convert(self):
        outputs = {}; feature_id_map, story_id_map = {}, {}
        feature_rows_by_project = {}
        story_rows_by_train = {}
        # RB: Defect-only per-train collector, mirroring story_rows_by_train so bugs
        # can be split with the same _write_split_files helper. Isolated to defects.
        bug_rows_by_train = {}
        # RB: Task-only per-train collector, mirroring story_rows_by_train so tasks
        # can be split with the same _write_split_files helper. Isolated to tasks.
        task_rows_by_train = {}
        feature_issue_type = "Feature" if self.use_roadmaps else "Epic"
        # RB: Epics are a distinct top level only when roadmaps levels are enabled
        # (Features are emitted as "Feature"). When use_roadmaps is False, Feature rows
        # are already written as Epics, so we skip the separate epics source to avoid
        # merging two artifact types into a single jira_epic.csv.
        epics = self.inputs.get("epics") if self.use_roadmaps else None
        if epics is not None:
            # Rally epics export uses underscore column names (e.g. "Created_By",
            # "Planned_End_Date"); normalize to spaces so _gather_common resolves them
            # exactly like the Feature/User Story inputs. This reuses the existing
            # mappings: Description+Notes -> Description, Owner -> Assignee, Created By
            # -> Reporter, Name -> Summary, Tags -> Labels, Planned End Date -> Due Date.
            epics = epics.rename(columns=lambda c: str(c).replace("_", " "))
            for _, r in epics.iterrows():
                # RB: Skip blank/padding rows (no Formatted ID) so empty export
                # rows are not converted into placeholder GEN-0 issues.
                if not str(get_col(r, "Formatted ID", "")).strip():
                    continue
                base, fid, _ = self._gather_common(r, "Epic", "Epic")
                base["Epic Name"] = base["Summary"]
                base["Rally ID"] = fid
                # RB: Pass the raw Rally "itpr" column through to the Jira "ITPR" field.
                base["ITPR"] = str(get_col(r, "ITPR", get_col(r, "itpr", ""))).strip()
                outputs.setdefault("Epic", []).append(base)
        feats = self.inputs.get("features")
        if feats is not None:
            feature_state_map = {
                "no entry": "Pending Approval",
                "backlog": "Pending Approval",
                "ask": "Defining",
                "prepare": "Defining",
                "ready": "Ready To Start",
                "in progress": "In-Progress",
                "in-progress": "In-Progress",
                "done": "Delivered",
            }
            for _, r in feats.iterrows():
                # RB: Skip blank/padding rows (no Formatted ID) so empty export
                # rows are not converted into placeholder GEN-0 issues.
                if not str(get_col(r, "Formatted ID", "")).strip():
                    continue
                issue_type = feature_issue_type
                print(f"issue_type: {issue_type}")
                base, fid, feature_train = self._gather_common(r, "Feature", issue_type, format_desc=True)
                epic_id, epic_name = split_parent_reference(get_col(r, "Parent Epic", ""))
                base["Epic ID"] = epic_id
                if epic_name:
                    base["Epic Name"] = epic_name
                #RB: add column for Comments
                base["Rally ID"] = fid
                # RB: Pass the raw Rally "Parent" column straight through to the Jira "Parent" field.
                base["Parent"] = str(get_col(r, "Parent", "")).strip()
                # RB: Pass the raw Rally Schedule State through to a dedicated
                # "Schedule State" column (separate from the mapped "Status").
                # Features use the "State" column; fall back accordingly.
                base["Schedule State"] = str(get_col(r, "Schedule State", get_col(r, "State", ""))).strip()
                feature_state = str(get_col(r, "State", "")).strip()
                feature_state_key = feature_state.lower().replace("_", " ").strip()
                base["State"] = feature_state_map.get(feature_state_key, feature_state)
                #print(f"fid>>>>inside features: {fid}")
                if issue_type == "Epic": base["Epic Name"] = base["Summary"]
                outputs.setdefault(issue_type, []).append(base)
                # RB: Split Features by their resolved train (case-insensitive) rather
                # than the raw project name so team-level projects roll up correctly.
                feature_train = str(feature_train).strip() or "Unassigned"
                feature_rows_by_project.setdefault(feature_train, []).append(base)
                if fid: feature_id_map[fid] = base["Issue Id"]
        stories = self.inputs.get("stories")
        if stories is not None:
            story_state_map = {
                "in-progress": "In-Progress",
                "need definition": "Defining",
                "needs definition": "Defining",
                "defined": "Ready To Start",
                "completed": "Test Complete",
                "accepted": "Accepted",
            }
            for _, r in stories.iterrows():
                # RB: Skip blank/padding rows (no Formatted ID) so empty export
                # rows are not converted into placeholder GEN-0 issues that all
                # collide on STORY-GEN-0 and land in jira_story_unassigned.csv.
                if not str(get_col(r, "Formatted ID", "")).strip():
                    continue
                base, fid, train_name = self._gather_common(r, "User Story", "Story", format_desc=True, desc_labels=STORY_DESC_LABELS, generic_desc=True)
                #RB: add column for Comments
                base["Rally ID"] = fid
                # RB: Pass the raw Rally "Parent" column straight through to the Jira "Parent" field.
                base["Parent"] = str(get_col(r, "Parent", "")).strip()
                # RB: Pass the raw Rally Schedule State through to a dedicated
                # "Schedule State" column (separate from the mapped "Status").
                base["Schedule State"] = str(get_col(r, "Schedule State", get_col(r, "State", ""))).strip()
                story_schedule_state = str(get_col(r, "Schedule State", get_col(r, "ScheduleState", ""))).strip()
                story_state_key = story_schedule_state.lower().replace("_", " ").strip()
                base["State"] = story_state_map.get(story_state_key, story_schedule_state)
                feature_id, feature_name = split_parent_reference(get_col(r, "Parent Feature", get_col(r, "Feature", "")))
                base["Feature ID"] = feature_id
                base["Feature Name"] = feature_name
                # RB: User Story "Parent Id" = parent Feature's Jira numeric ID.
                # Extract the Feature number (e.g. "F231056") from the Rally
                # "Parent Feature" column (e.g. "Feature F231056: ...") and look up
                # its Jira ID via mappings/feature_to_jira_id.csv. Features not yet in
                # Jira (unmapped) leave Parent Id empty.
                portfolio_item = str(get_col(r, "Parent Feature", "")).strip()
                pf_match = re.search(r"(F\d+)", portfolio_item)
                parent_feature_fid = pf_match.group(1) if pf_match else ""
                base["Parent Id"] = self.feature_to_jira_id.get(parent_feature_fid, "")
                #print(f"base_parent_id: {base['Parent Id']}")
                #print(f"base: {base}")
                outputs.setdefault("Story", []).append(base)
                story_rows_by_train.setdefault(train_name or "Unassigned", []).append(base)
                if fid: story_id_map[fid] = base["Issue Id"]
        tasks = self.inputs.get("tasks")
        if tasks is not None:
            for _, r in tasks.iterrows():
                # RB: Skip blank/padding rows (no Formatted ID) so empty export
                # rows are not converted into placeholder GEN-0 issues.
                if not str(get_col(r, "Formatted ID", "")).strip():
                    continue
                target_type = self.cfg.get("task_target_type", "Sub-task")
                base, fid, train_name = self._gather_common(r, "Task", target_type)
                #RB: add column for Comments
                base["Rally ID"] = fid
                # RB: Pass the raw Rally "Parent" column straight through to the Jira "Parent" field.
                base["Parent"] = str(get_col(r, "Parent", "")).strip()
                # RB: Task-only pass-through of the raw Rally "Link" column to the Jira "Link" field.
                base["Link"] = str(get_col(r, "Link", "")).strip()
                #parent_fid = str(get_col(r, "WorkProduct", get_col(r, "Parent", ""))).strip()
                parent_fid = str(get_col(r, "Parent", get_col(r, "User Story", ""))).strip()
                pid = story_id_map.get(parent_fid, feature_id_map.get(parent_fid, ""))
                if pid.startswith("STORY-"):
                    pid = pid.replace("STORY-", "")
                else:
                    pid = pid
                print(f"pid: {pid}")
                base["Parent Id"] = pid
                outputs.setdefault(target_type, []).append(base)
                # RB: Task-only per-train split, using the same helper/resolution
                # (train_name from _project_to_train) as stories and bugs.
                task_rows_by_train.setdefault(train_name or "Unassigned", []).append(base)
        defects = self.inputs.get("defects")
        if defects is not None:
            defect_state_map = {
                "submitted": "PENDING APPROVAL",
                "open": "IN PROGRESS",
                "fixed": "TEST COMPLETE",
                "closed": "ACCEPTED",
                "reopened": "IN PROGRESS",
            }
            defect_priority_map = {
                "resolved immediately": "Highest",
                "resolve immediately": "Highest",
                "high attention": "High",
                "normal": "Medium",
                "low": "Low",
            }
            defect_root_cause_map = {
                "none": "NA",
                "code": "Coding",
                "configuration": "Configuration",
                "converted": "Enhancement",
                "data": "Data Quality",
                "duplicate": "NA",
                "environment": "Environment",
                "integration": "External Vendor",
                "not a defect": "Requirement",
                "performance": "Performance Defect",
                "postponed": "NA",
                "requirements": "Requirement",
                "security": "Incorrect Design",
                "unknown": "NA",
                "ux/ui": "UX Gap",
                "won't fix": "NA",
                "auto-generated": "NA",
                "auto generated": "NA",
                "api": "Coding",
                "internal": "Prod Issue",
                "external": "External Vendor",
            }
            for _, r in defects.iterrows():
                # RB: Skip blank/padding rows (no Formatted ID) so empty export
                # rows are not converted into placeholder GEN-0 issues.
                if not str(get_col(r, "Formatted ID", "")).strip():
                    continue
                base, fid, train_name = self._gather_common(
                    r,
                    "Defect",
                    "Defect",
                    format_desc=True,
                    desc_labels=DEFECT_DESC_LABELS,
                    generic_desc=False,
                    force_desc_labels=True,
                )
                #RB: add column for Comments
                base["Rally ID"] = fid
                # RB: Defect-only state mapping.
                # Map Rally State -> Jira State using explicit values.
                defect_state = str(get_col(r, "State", "")).strip()
                base["State"] = defect_state_map.get(defect_state.lower(), defect_state)
                # RB: Defect-only field overrides. Applied here (not in _gather_common)
                # so Feature/Story/Epic/Task outputs are completely unaffected.
                #  - Priority: map Rally "Priority" to Jira Priority using explicit
                #    defect values (do NOT fall back to Severity).
                #  - Opened Date  -> Start Date
                #  - Target Date  -> Due Date
                #  - SNOW Incident Number -> appended to Labels
                #  - Resolution   -> Root Cause
                #  - Environment  -> Environment
                #  - RCA -> RCA
                #  - Severity     -> Severity
                defect_priority = str(get_col(r, "Priority", "")).strip()
                base["Priority"] = defect_priority_map.get(defect_priority.lower(), defect_priority)
                base["Severity"] = str(get_col(r, "Severity", "")).strip()
                base["Start Date"] = format_date(get_col(r, "Opened Date", "")) or ""
                base["Due Date"] = format_date(get_col(r, "Target Date", "")) or ""
                base["Environment"] = str(get_col(r, "Environment", "")).strip()
                base["RCA"] = str(get_col(r, "RCA", "")).strip()
                # RB: Pass the raw Rally "Link" column straight through to the Jira "Link" field.
                base["Link"] = str(get_col(r, "Link", "")).strip()
                defect_resolution = str(get_col(r, "Resolution", "")).strip()
                defect_resolution_key = defect_resolution.lower().replace("’", "'").replace("‑", "-").replace("–", "-").replace("—", "-").strip()
                base["Root Cause"] = defect_root_cause_map.get(defect_resolution_key, defect_resolution)
                snow = str(get_col(r, "SNOW Incident Number", "")).strip()
                if snow:
                    snow_label = normalize_labels(snow)
                    base["Labels"] = f"{base['Labels']} {snow_label}".strip() if base["Labels"] else snow_label
                outputs.setdefault("Bug", []).append(base)
                # RB: Defect-only per-train split, using the same helper/resolution
                # (train_name from _project_to_train) as stories.
                bug_rows_by_train.setdefault(train_name or "Unassigned", []).append(base)
        if self.cfg.get("test_mode", "custom") != "none":
            tcs = self.inputs.get("testcases")
            if tcs is not None:
                for _, r in tcs.iterrows():
                    # RB: Skip blank/padding rows (no Formatted ID).
                    if not str(get_col(r, "Formatted ID", "")).strip():
                        continue
                    base, fid, _ = self._gather_common(r, "Test Case", "Test Case")
                    parent_fid = str(get_col(r, "WorkProduct", get_col(r, "Requirement", ""))).strip()
                    if parent_fid in story_id_map: base["Parent Id"] = story_id_map[parent_fid]
                    outputs.setdefault("Test Case", []).append(base)
            tsets = self.inputs.get("testsets")
            if tsets is not None:
                for _, r in tsets.iterrows():
                    # RB: Skip blank/padding rows (no Formatted ID).
                    if not str(get_col(r, "Formatted ID", "")).strip():
                        continue
                    base, fid, _ = self._gather_common(r, "Test Set", "Test Set")
                    outputs.setdefault("Test Set", []).append(base)
        order = list(outputs.keys()); self.out_dir.mkdir(parents=True, exist_ok=True)
        # RB: The Jira issue type used for Rally tasks (default "Sub-task"); its
        # per-type file is written with the reduced TASK_COLUMNS set only.
        task_target_type = self.cfg.get("task_target_type", "Sub-task")
        for issue_type in order:
            out_cols = TASK_COLUMNS if issue_type == task_target_type else JIRA_BASE_COLUMNS
            df = pd.DataFrame(outputs[issue_type]); df = ensure_cols(df, JIRA_BASE_COLUMNS); df = df[out_cols]
            df = expand_repeated_column(df, "Milestones")
            (self.out_dir / f"jira_{issue_type.replace(' ', '_').lower()}.csv").write_text(df.to_csv(index=False), encoding="utf-8-sig")
        self._write_split_files(feature_rows_by_project, f"jira_{feature_issue_type.replace(' ', '_').lower()}")
        self._write_split_files(story_rows_by_train, "jira_story")
        # RB: Task-only per-train split reusing the same writer as feature/story,
        # restricted to TASK_COLUMNS so task-excluded columns are dropped.
        self._write_split_files(task_rows_by_train, "jira_task", columns=TASK_COLUMNS)
        # RB: Defect-only per-train split reusing the same writer as feature/story.
        self._write_split_files(bug_rows_by_train, "jira_bug")
        if self.cfg.get("emit_consolidated", True):
            frames = []
            for issue_type in order:
                df = pd.DataFrame(outputs[issue_type]); df["__it__"] = issue_type; frames.append(df)
            if frames:
                big = pd.concat(frames, ignore_index=True); big = ensure_cols(big, JIRA_BASE_COLUMNS); big = big[JIRA_BASE_COLUMNS]
                big = expand_repeated_column(big, "Milestones")
                (self.out_dir / "jira_all_issues.csv").write_text(big.to_csv(index=False), encoding="utf-8-sig")
        print("Conversion complete."); return 0
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", required=True); ap.add_argument("--in", dest="in_dir", required=True); ap.add_argument("--out", dest="out_dir", required=True)
    args = ap.parse_args(); cfg = yaml.safe_load(Path(args.config).read_text()); conv = Converter(cfg, Path(args.in_dir), Path(args.out_dir)); sys.exit(conv.convert())
if __name__ == "__main__": main()

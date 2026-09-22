"""Rally description heading formatter — ported from rally_to_jira.py.

Rally feature/story/defect descriptions embed section headings inline (e.g.
"Business Value: ... In Scope ... Out of Scope: ..."). ``format_description``
detects the headings ALREADY present, puts each on its own line, keeps their
original names/order, de-duplicates repeated headings, and adds nothing new.
Applied per artifact type via ``format_for_type`` so Feature/User Story/Defect
descriptions read cleanly in the generated Jira files.
"""
from __future__ import annotations

import re

# Feature (and generic) headings.
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

# User-story-only heading set (applied with generic ':' detection).
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

# Defect-only heading set (split on labels even without a trailing colon).
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
    # Strip stray markdown emphasis/heading markers so headings detect cleanly.
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
        pat = _desc_pattern(labels)
        for m in pat.finditer(raw):
            i = m.start()
            prev = raw[i - 1] if i > 0 else ""
            is_head = (i == 0) or prev in ("\u00a0", "\n", "\r") or m.group(2) == ":"
            if not is_head:
                continue
            label = m.group(1).strip().rstrip(":").strip()
            marks.append((m.start(), m.end(), label, _desc_key(m.group(1), labels), False))

    # 2) Generic "<label>:" headings (stories).
    if generic:
        for cm in re.finditer(r":", raw):
            ci = cm.start()
            after = raw[ci + 1:ci + 2]
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
        end = filtered[idx + 1][0] if idx + 1 < len(filtered) else len(raw2)
        content = _desc_clean(raw2[e:end])
        parts.append(f"{label}:\n{content}" if content else f"{label}:")
    return "\n\n".join(parts).strip()


def format_for_type(text: str, artifact_type: str) -> str:
    """Apply the right heading set per artifact type (Feature/User Story/Defect).

    Epic/Task/Test and unknown types keep their description text unchanged —
    matching rally_to_jira.py's per-type behaviour.
    """
    t = (artifact_type or "").strip().lower()
    if t == "feature":
        return format_description(text, DESC_LABELS)
    if t in ("user story", "story"):
        return format_description(text, STORY_DESC_LABELS, generic=True)
    if t in ("defect", "bug"):
        return format_description(text, DEFECT_DESC_LABELS, force_known=True)
    return text

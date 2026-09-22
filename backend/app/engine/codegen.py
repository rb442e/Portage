"""Generate a readable, runnable Python module from a mapping template.

Consolidates every artifact's field mapping into one versioned file — the
"newly generated rally_to_jira" the user can read and keep. It is a faithful
projection of the template the migration engine already executes.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "mapping").strip().lower()).strip("_")
    return s or "mapping"


def _pylist(items: List[str]) -> str:
    return "[" + ", ".join('"' + str(i).replace('"', '\\"') + '"' for i in items) + "]"


def _rules_block(maps: List[dict]) -> str:
    lines = []
    for m in maps:
        sources = m.get("sources") or ([m["source"]] if m.get("source") else [])
        target = m.get("target", "")
        transform = m.get("transform", "") or ""
        st, tt = m.get("source_type") or "?", m.get("target_type") or "?"
        comment = f"  # {st} -> {tt}"
        if m.get("note"):
            comment += f" ({m['note']})"
        lines.append(
            f'        {{"sources": {_pylist(sources)}, "target": "{target}", '
            f'"transform": "{transform}"}},{comment}'
        )
    return "\n".join(lines) if lines else "        # (no fields mapped)"


def _value_maps_block(value_maps: List[dict]) -> str:
    parts = []
    for vm in value_maps:
        field = vm.get("field")
        inner = ",\n".join(f'        "{k}": "{v}"' for k, v in (vm.get("values", {}) or {}).items())
        parts.append(f'    "{field}": {{\n{inner}\n    }},')
    return "\n".join(parts) if parts else "    # (no value maps)"


def generate_python(template: Dict) -> Dict[str, str]:
    name = template.get("name", "mapping")
    version = template.get("version", 1)
    profiles = template.get("profiles", {}) or {}
    value_maps = template.get("value_maps", []) or []
    artifacts = list(profiles.keys())
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    profiles_src = "\n".join(
        f'    "{atype}": [\n{_rules_block(maps)}\n    ],' for atype, maps in profiles.items()
    )
    vm_src = _value_maps_block(value_maps)

    code = f'''"""
Portage mapping — "{name}" (v{version})
Generated {ts}. Consolidated Rally -> Jira field mapping across artifacts:
{", ".join(artifacts) or "(none)"}.

This module is generated from the Portage Mapping Studio. Regenerate there
rather than hand-editing.
"""
import csv
import re
import sys

# Rally value -> Jira value translations, applied per target field.
VALUE_MAPS = {{
{vm_src}
}}

# Ordered field rules per artifact type. `sources` are tried in order; the first
# non-empty column wins (coalesce). `transform` is one of "", "labels",
# "number", "date".
PROFILES = {{
{profiles_src}
}}


def _first(row, sources):
    for s in sources:
        v = str(row.get(s, "") or "").strip()
        if v:
            return v
    return ""


def _labels(v):
    parts = [x.strip() for x in re.split(r"[;,]", v) if x.strip()]
    return parts or ([v] if v else [])


def _number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def map_row(row, artifact):
    """Map one Rally row (dict) to Jira fields for the given artifact type."""
    out = {{}}
    for rule in PROFILES.get(artifact, []):
        value = _first(row, rule["sources"])
        transform = rule.get("transform")
        if transform == "labels":
            value = _labels(value)
        elif transform == "number":
            value = _number(value)
        vm = VALUE_MAPS.get(rule["target"])
        if vm and isinstance(value, str) and value in vm:
            value = vm[value]
        out[rule["target"]] = value
    return out


if __name__ == "__main__":
    artifact = sys.argv[1] if len(sys.argv) > 1 else (list(PROFILES) or ["Feature"])[0]
    path = sys.argv[2] if len(sys.argv) > 2 else ""
    if not path:
        print("Usage: python this_file.py <artifact> <rally_export.csv>")
        sys.exit(1)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            print(map_row(r, artifact))
'''
    return {"filename": f"portage_mapping_{_slug(name)}_v{version}.py",
            "code": code, "language": "python"}

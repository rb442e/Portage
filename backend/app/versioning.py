"""Pure diff helpers for catalogs and mapping templates (no I/O)."""
from __future__ import annotations

from typing import Any, Dict, List


def diff_entries(old: Dict[str, str], new: Dict[str, str]) -> Dict[str, Any]:
    added = {k: v for k, v in new.items() if k not in old}
    removed = {k: v for k, v in old.items() if k not in new}
    changed = {k: {"from": old[k], "to": new[k]} for k in new if k in old and old[k] != new[k]}
    return {"added": added, "removed": removed, "changed": changed,
            "summary": f"+{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed"}


def _sources(fm: Dict[str, Any]) -> List[str]:
    return list(fm.get("sources") or ([fm["source"]] if fm.get("source") else []))


def diff_mappings(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Per-artifact field-map differences keyed by Jira target field."""
    out: Dict[str, Any] = {}
    old_p, new_p = old.get("profiles") or {}, new.get("profiles") or {}
    total = 0
    for artifact in sorted(set(old_p) | set(new_p)):
        o = {m["target"]: m for m in old_p.get(artifact, [])}
        n = {m["target"]: m for m in new_p.get(artifact, [])}
        added = {t: _sources(n[t]) for t in n if t not in o}
        removed = {t: _sources(o[t]) for t in o if t not in n}
        changed = {t: {"from": _sources(o[t]), "to": _sources(n[t])}
                   for t in n if t in o and (_sources(o[t]) != _sources(n[t])
                                             or o[t].get("transform", "") != n[t].get("transform", ""))}
        if added or removed or changed:
            out[artifact] = {"added": added, "removed": removed, "changed": changed}
            total += len(added) + len(removed) + len(changed)
    old_vm = {v["field"]: v.get("values", {}) for v in old.get("value_maps") or []}
    new_vm = {v["field"]: v.get("values", {}) for v in new.get("value_maps") or []}
    value_maps = {f: diff_entries(old_vm.get(f, {}), new_vm.get(f, {}))
                  for f in sorted(set(old_vm) | set(new_vm)) if old_vm.get(f, {}) != new_vm.get(f, {})}
    total += len(value_maps)
    return {"artifacts": out, "value_maps": value_maps,
            "summary": f"{total} change(s)" if total else "No differences"}

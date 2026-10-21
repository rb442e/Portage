"""Knowledge graph over Portage's own data, for graph-grounded retrieval (GraphRAG).

The graph is derived deterministically from the store (no LLM extraction, so it is exact and
reproducible) and rebuilt on every call, so answers always reflect current data.

Nodes:  artifacts, mappings, Rally/Jira fields, value maps, catalogs (+ entries, versions),
        uploaded sources and columns, jobs and error clusters.
Edges:  covers, populates, feeds, supersedes, has_value_map, translates, contains, has_version,
        has_column, same_as, needs_catalog, hit_error, mentions.

Retrieval: seed nodes by text match (rarity-weighted) -> multi-hop expansion with fan-out limits ->
compact subgraph + linked documentation. `overview()` gives corpus-level summaries per community
(artifact, catalog, jobs) for "global" questions.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .. import product_settings, store
from ..config import settings as app_settings
from ..engine.mapping import ARTIFACT_TYPES
from . import knowledge

_STOP = frozenset("""the an and or of to in on for with is are was were be been what which who how why does did my our
this that these those from by at as it its about show tell give list find please can you any all""".split())
_VERSIONED = re.compile(r"^jira_([a-z]+)_mapping_v(\d+)$")
_SLUG_ARTIFACT = {"epic": "Epic", "feature": "Feature", "us": "User Story", "task": "Task", "defect": "Defect"}
_KIND_FIELDS = {"sprint": {"sprint"}, "version": {"fix_versions", "fix_version", "affects_versions"},
                "user": {"assignee", "reporter", "owner"}, "team": {"team"}}
_KIND_COLUMNS = {"sprint": ("iteration", "sprint"), "version": ("release", "milestone", "fix version"),
                 "user": ("owner", "submitted by"), "team": ("team",)}
_TYPE_DOC = {"mapping": "Mapping Studio", "catalog": "Jira Catalog", "valuemap": "Value maps", "job": "Migration"}
_TYPE_ORDER = ["mapping", "catalog", "jira_field", "rally_field", "job", "error", "valuemap", "source", "column",
               "artifact", "catalog_version", "entry"]
FANOUT = 5   # neighbours followed per relation per node
SEED_MIN_RATIO = 0.6   # a seed must score at least this fraction of the best match
RESULT_BUDGET = 5500   # characters; the agent truncates tool results at 6,000
_BULK_RELATIONS = frozenset({"populates", "contains", "has_column"})   # followed only toward query matches
_FAILURE_WORDS = frozenset({"fail", "error", "problem", "broke", "wrong", "missing", "unmapped"})


@dataclass
class Node:
    id: str
    type: str
    label: str
    props: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    props: Dict[str, Any] = field(default_factory=dict)


class Graph:
    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[Tuple[str, str, str], Edge] = {}
        self._adj: Dict[str, List[Edge]] = defaultdict(list)

    def add_node(self, nid: str, type_: str, label: str, **props: Any) -> Node:
        node = self.nodes.get(nid)
        if node is None:
            node = self.nodes[nid] = Node(nid, type_, label, dict(props))
        else:
            node.props.update(props)
        return node

    def add_edge(self, src: str, rel: str, dst: str, **props: Any) -> Optional[Edge]:
        if src not in self.nodes or dst not in self.nodes:
            return None
        key = (src, rel, dst)
        edge = self.edges.get(key)
        if edge is None:
            edge = self.edges[key] = Edge(src, rel, dst, dict(props))
            self._adj[src].append(edge)
            self._adj[dst].append(edge)
        else:
            edge.props.update(props)
        return edge

    def adjacent(self, nid: str) -> List[Edge]:
        return self._adj.get(nid, [])

    def related(self, nid: str, rel: str, outgoing: bool = True) -> List[Node]:
        out = []
        for e in self.adjacent(nid):
            if e.rel == rel and ((e.src == nid) if outgoing else (e.dst == nid)):
                out.append(self.nodes[e.dst if outgoing else e.src])
        return out

    def of_type(self, type_: str) -> List[Node]:
        return [n for n in self.nodes.values() if n.type == type_]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
def _add_mappings(g: Graph) -> None:
    by_slug: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for m in store.list_mappings():
        mid, name = f"mapping:{m['id']}", m.get("name", "")
        vm = _VERSIONED.match(name)
        slug_art = _SLUG_ARTIFACT.get(vm.group(1)) if vm else None
        g.add_node(mid, "mapping", name, version=int(vm.group(2)) if vm else m.get("version", 1),
                   description=(m.get("description") or "")[:100])
        if vm and slug_art:
            by_slug[vm.group(1)].append((int(vm.group(2)), mid))
        for art, maps in (m.get("profiles") or {}).items():
            if not maps or (slug_art and art != slug_art):   # a versioned name only owns its artifact
                continue
            g.add_node(f"artifact:{art}", "artifact", art)
            g.add_edge(mid, "covers", f"artifact:{art}")
            for fm in maps:
                target = fm.get("target")
                if not target:
                    continue
                sources = [s for s in (fm.get("sources") or [fm.get("source")]) if s]
                jid = f"jira_field:{art}:{target}"
                g.add_node(jid, "jira_field", f"{target} ({art})", key=target, artifact=art,
                           data_type=fm.get("target_type", ""))
                g.add_edge(mid, "populates", jid, sources=sources, transform=fm.get("transform", ""))
                for s in sources:
                    rid = f"rally_field:{art}:{s}"
                    g.add_node(rid, "rally_field", f"{s} ({art})", key=s, artifact=art)
                    feeds = g.add_edge(rid, "feeds", jid)
                    if feeds is not None:
                        names = feeds.props.setdefault("mappings", [])
                        if name not in names:
                            names.append(name)
        for vmap in m.get("value_maps") or []:
            values = vmap.get("values") or {}
            if not vmap.get("field") or not values:
                continue
            vid = f"valuemap:{m['id']}:{vmap['field']}"
            g.add_node(vid, "valuemap", f"value map: {vmap['field']}", values=len(values),
                       sample="; ".join(f"{k} -> {v}" for k, v in list(values.items())[:6]))
            g.add_edge(mid, "has_value_map", vid)
    for versions in by_slug.values():
        versions.sort()
        for (_, older), (_, newer) in zip(versions, versions[1:]):
            g.add_edge(newer, "supersedes", older)


def _add_catalogs(g: Graph) -> None:
    jira_fields = g.of_type("jira_field")
    for c in store.list_lookups():
        cid, kind = f"catalog:{c['id']}", c.get("kind", "")
        g.add_node(cid, "catalog", c["name"], kind=kind, entries=len(c["entries"]))
        for jf in jira_fields:
            if jf.props["key"] in _KIND_FIELDS.get(kind, ()):
                g.add_edge(cid, "translates", jf.id)
        for src, tgt in c["entries"].items():
            eid = f"entry:{c['id']}:{src}"
            g.add_node(eid, "entry", f"{src} -> {tgt}", source=src, target=tgt, kind=kind)
            g.add_edge(cid, "contains", eid)
        for v in store.list_versions("lookup", c["id"])[:6]:
            vid = f"catalog_version:{c['id']}:{v['version']}"
            g.add_node(vid, "catalog_version", f"{c['name']} v{v['version']}", version=v["version"],
                       author=v["author"], message=(v["message"] or "")[:100], when=v["created_at"], size=v["size"])
            g.add_edge(cid, "has_version", vid)


def _add_sources(g: Graph) -> None:
    rally_by_name: Dict[str, List[str]] = defaultdict(list)
    for n in g.of_type("rally_field"):
        rally_by_name[n.props["key"].lower()].append(n.id)
    catalogs_by_kind: Dict[str, List[str]] = defaultdict(list)
    for n in g.of_type("catalog"):
        catalogs_by_kind[n.props["kind"]].append(n.id)
    files = sorted((p for p in app_settings.upload_dir.glob("*.csv") if re.fullmatch(r"[0-9a-f]{32}", p.stem)),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    for p in files:
        try:
            with p.open(encoding="utf-8-sig", errors="ignore", newline="") as fh:
                header = next(csv.reader(fh), [])
        except OSError:
            continue
        sid = f"source:{p.stem}"
        g.add_node(sid, "source", f"upload {p.stem[:8]}", source_id=p.stem, columns=len(header))
        for col in (c.strip() for c in header):
            if not col:
                continue
            low = col.lower()
            g.add_node(f"column:{low}", "column", col)
            g.add_edge(sid, "has_column", f"column:{low}")
            for rid in rally_by_name.get(low, []):
                g.add_edge(f"column:{low}", "same_as", rid)
            for kind, cols in _KIND_COLUMNS.items():
                if low in cols:
                    for cat in catalogs_by_kind.get(kind, []):
                        g.add_edge(f"column:{low}", "needs_catalog", cat)


def _link_mentions(g: Graph, error_id: str, text: str, limit: int = 4) -> None:
    """Connect an error cluster to the catalogs and Jira fields its message names."""
    low, seen, links = text.lower(), set(), 0
    for n in g.nodes.values():
        if links >= limit:
            break
        if n.type == "catalog" and n.props["kind"] and re.search(rf"\b{re.escape(n.props['kind'])}s?\b", low):
            g.add_edge(error_id, "mentions", n.id)
            links += 1
        elif n.type == "jira_field" and n.props["key"] not in seen:
            key = n.props["key"]
            if re.search(rf"\b{re.escape(key.replace('_', ' '))}\b|\b{re.escape(key)}\b", low):
                seen.add(key)
                g.add_edge(error_id, "mentions", n.id)
                links += 1


def _add_jobs(g: Graph) -> None:
    for j in store.list_jobs(10):
        jid = f"job:{j.get('job_id', '')}"
        g.add_node(jid, "job", f"job {jid[4:12]} ({j.get('state')})", state=j.get("state"),
                   dry_run=bool(j.get("dry_run")), total=j.get("total", 0), created=j.get("created", 0),
                   failed=j.get("failed", 0), started=j.get("started_at", ""))
        clusters: Counter = Counter()
        for it in j.get("items") or []:
            if it.get("status") == "failed" and it.get("message"):
                clusters[re.sub(r"\d+", "#", it["message"]).strip()[:140]] += 1
        for msg, n in clusters.most_common(5):
            eid = f"error:{msg}"
            node = g.add_node(eid, "error", msg)
            node.props["occurrences"] = node.props.get("occurrences", 0) + n
            g.add_edge(jid, "hit_error", eid)
            _link_mentions(g, eid, msg)


def build() -> Graph:
    g = Graph()
    for art in ARTIFACT_TYPES:
        g.add_node(f"artifact:{art}", "artifact", art)
    _add_mappings(g)
    _add_catalogs(g)
    _add_sources(g)
    _add_jobs(g)
    return g


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def _stem(t: str) -> str:
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    for suffix in ("ing", "ed"):
        if len(t) > 5 and t.endswith(suffix):
            return t[:-len(suffix)]
    return t


def _tokens(text: str) -> List[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in _STOP and (len(t) >= 3 or any(c.isdigit() for c in t))]


def _scores(g: Graph, query: str) -> Dict[str, float]:
    q_tokens, q_low = set(_tokens(query)), query.lower()
    if not q_tokens:
        return {}
    failure_intent = bool(q_tokens & _FAILURE_WORDS)
    label_toks = {nid: set(_tokens(n.label)) for nid, n in g.nodes.items()}
    df = Counter(t for toks in label_toks.values() for t in toks)
    total = len(g.nodes)
    out: Dict[str, float] = {}
    for nid, n in g.nodes.items():
        prop_toks = set(_tokens(" ".join(str(v) for v in n.props.values() if isinstance(v, (str, int)))))
        s = 0.0
        for t in q_tokens:
            w = math.log(1 + total / max(df.get(t, 1), 1))   # rare terms count more
            if t in label_toks[nid]:
                s += 3 * w
            elif t in prop_toks:
                s += w
        if len(n.label) >= 4 and n.label.lower() in q_low:
            s += 5
        if failure_intent and n.type == "error" and s > 0:   # "why did X fail" should land on the error cluster
            s += 6
        if s > 0:
            out[nid] = s
    return out


def _brief(props: Dict[str, Any]) -> str:
    parts = []
    for k, v in props.items():
        if v in ("", None, [], {}):
            continue
        if isinstance(v, list):
            v = ", ".join(map(str, v[:4]))
        parts.append(f"{k}={str(v)[:70]}")
    return ", ".join(parts[:5])


def _fmt_node(n: Node) -> str:
    info = _brief(n.props)
    return f"{n.type}:{n.label}" + (f" [{info}]" if info else "")


def _fmt_edge(g: Graph, e: Edge) -> str:
    extra = ""
    if e.props.get("sources"):
        extra = f" [from {', '.join(e.props['sources'])}" + (f", transform {e.props['transform']}" if e.props.get("transform") else "") + "]"
    elif e.props.get("mappings"):
        extra = f" [via {', '.join(e.props['mappings'][:3])}]"
    return f"{g.nodes[e.src].type}:{g.nodes[e.src].label} --{e.rel}--> {g.nodes[e.dst].type}:{g.nodes[e.dst].label}{extra}"


def _expand(g: Graph, seeds: List[str], scores: Dict[str, float], depth: int, max_nodes: int) -> Tuple[Dict[str, int], int]:
    keep: Dict[str, int] = {s: 0 for s in seeds}
    omitted, frontier = 0, deque(seeds)
    while frontier:
        nid = frontier.popleft()
        if keep[nid] >= depth:
            continue
        by_rel: Dict[Tuple[str, bool], List[str]] = defaultdict(list)
        for e in g.adjacent(nid):
            by_rel[(e.rel, e.src == nid)].append(e.dst if e.src == nid else e.src)
        for (rel, _out), others in by_rel.items():
            fresh = sorted({o for o in others if o not in keep}, key=lambda o: (-scores.get(o, 0), g.nodes[o].label))
            if rel in _BULK_RELATIONS:   # e.g. all 30 fields of a mapping: only the ones the question is about
                omitted += sum(1 for o in fresh if not scores.get(o))
                fresh = [o for o in fresh if scores.get(o)]
            omitted += max(0, len(fresh) - FANOUT)
            for o in fresh[:FANOUT]:
                if len(keep) >= max_nodes:
                    omitted += 1
                    continue
                keep[o] = keep[nid] + 1
                frontier.append(o)
    return keep, omitted


def _facts(g: Graph, edges: List[Edge], keep: Dict[str, int]) -> List[str]:
    """Plain-English statements of the most useful relationships, so a small model need not read raw edges."""
    nearest = sorted(edges, key=lambda e: keep[e.src] + keep[e.dst])
    out: List[str] = []
    for e in nearest:
        s, d = g.nodes[e.src], g.nodes[e.dst]
        if e.rel == "feeds":
            out.append(f"Rally field '{s.props['key']}' feeds Jira field '{d.props['key']}' ({d.props['artifact']}) in "
                       + ", ".join(e.props.get("mappings", [])[:3]))
        elif e.rel == "translates":
            out.append(f"The {s.props['kind']} catalog '{s.label}' translates values for Jira field '{d.props['key']}'; it is a catalog, not a Rally field")
        elif e.rel == "mentions" and s.type == "error":
            out.append(f"Failure '{s.label}' ({s.props.get('occurrences', 0)} items) involves {d.type.replace('_', ' ')} '{d.label}'")
        elif e.rel == "supersedes":
            out.append(f"Mapping '{s.label}' replaces the older '{d.label}'")
    return out[:8]


def search(query: str, depth: Optional[int] = None, max_nodes: Optional[int] = None) -> Dict[str, Any]:
    """Graph-grounded retrieval: best-matching items, their multi-hop neighbourhood, and linked docs.

    Depth and size default to the GraphRAG settings.
    """
    cfg = product_settings.get("graph")
    depth = depth or cfg["default_depth"]
    max_nodes = max_nodes or cfg["max_nodes"]
    g = build()
    scores = _scores(g, query)
    ranked = sorted(scores, key=lambda n: (-scores[n], _TYPE_ORDER.index(g.nodes[n].type)
                                           if g.nodes[n].type in _TYPE_ORDER else 99, g.nodes[n].label))
    seeds = [n for n in ranked[:4] if scores[n] >= SEED_MIN_RATIO * scores[ranked[0]]]   # drop weak side matches
    keep, omitted = _expand(g, seeds, scores, max(1, min(depth, 3)), max_nodes)
    edges = sorted((e for e in g.edges.values() if e.src in keep and e.dst in keep),
                   key=lambda e: (keep[e.src] + keep[e.dst], -(scores.get(e.src, 0) + scores.get(e.dst, 0))))[:30]

    docs: List[Dict[str, str]] = knowledge.search(query, 2)
    present = {g.nodes[n].type for n in keep}
    for type_, heading in _TYPE_DOC.items():
        if type_ in present and all(d["heading"] != heading for d in docs):
            text = next((t for h, t in knowledge.GLOSSARY if h == heading), "")
            if text:
                docs.append({"source": "Portage guide", "heading": heading, "text": text})
    result = {"query": query, "seeds": [_fmt_node(g.nodes[s]) for s in seeds],
              "facts": _facts(g, edges, keep),
              "relationships": [_fmt_edge(g, e) for e in edges],
              "nodes": [_fmt_node(g.nodes[n]) for n in keep if n not in seeds],
              "docs": [{"heading": d["heading"], "text": d["text"][:300]} for d in docs[:3]],
              "stats": {"graph_nodes": len(g.nodes), "graph_edges": len(g.edges), "returned_nodes": len(keep),
                        "omitted_neighbours": omitted}}
    return _fit(result)


def _fit(result: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the least relevant tail (nodes, then relationships) until the result fits the budget."""
    while len(json.dumps(result)) > RESULT_BUDGET and (result["nodes"] or len(result["relationships"]) > 5):
        result["stats"]["trimmed"] = True
        (result["nodes"] or result["relationships"]).pop()
    return result


def overview() -> Dict[str, Any]:
    """Corpus-level summary per community (artifact, catalog, jobs) for broad 'what is the state of...' questions."""
    g = build()
    artifacts = []
    for a in g.of_type("artifact"):
        maps = sorted(g.related(a.id, "covers", outgoing=False), key=lambda m: m.props.get("version", 0), reverse=True)
        if not maps:
            continue
        latest = maps[0]
        fields = [f for f in g.related(latest.id, "populates") if f.props.get("artifact") == a.label]
        artifacts.append({"artifact": a.label, "mapping_versions": len(maps), "latest": latest.label,
                          "mapped_fields_in_latest": len(fields)})
    catalogs = []
    for c in g.of_type("catalog"):
        versions = sorted(g.related(c.id, "has_version"), key=lambda v: v.props["version"], reverse=True)
        last = versions[0].props if versions else {}
        catalogs.append({"catalog": c.label, "kind": c.props["kind"], "entries": c.props["entries"],
                         "versions": len(versions), "last_change_by": last.get("author", ""),
                         "last_change": last.get("message", "")})
    jobs_ = g.of_type("job")
    errors = sorted(g.of_type("error"), key=lambda n: n.props.get("occurrences", 0), reverse=True)[:5]
    return {"artifacts": artifacts, "catalogs": catalogs,
            "jobs": {"count": len(jobs_), "by_state": dict(Counter(j.props.get("state") for j in jobs_)),
                     "top_errors": [{"error": e.label, "occurrences": e.props.get("occurrences", 0),
                                     "related": [n.label for n in g.related(e.id, "mentions")]} for e in errors]},
            "uploads": len(g.of_type("source")),
            "stats": {"nodes": len(g.nodes), "edges": len(g.edges)}}

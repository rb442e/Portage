"""Rally rich-text (HTML) -> Jira description converters.

Rally stores Description as HTML, including real ``<table>`` markup. The CSV
export flattens tables into run-together text, so the only faithful source is
Rally's API. These converters turn that HTML into the two shapes Jira accepts:

  * ``html_to_adf``  -> Atlassian Document Format (Jira Cloud, REST v3), with
    native ADF ``table`` nodes so the table renders in the same grid format.
  * ``html_to_wiki`` -> Jira wiki markup (Server / Data Center, REST v2), with
    ``||header||`` / ``|cell|`` table rows.

Stdlib only (``html.parser``) — no extra dependency. Focused on the elements
that appear in Rally descriptions: paragraphs, line breaks, headings, lists,
links, bold/italic/code, and tables.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

_VOID = {"br", "img", "hr", "input", "meta", "link", "col"}
_INLINE_MARK = {
    "strong": "strong", "b": "strong",
    "em": "em", "i": "em",
    "code": "code",
    "u": "underline",
    "s": "strike", "strike": "strike", "del": "strike",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INLINE_TAGS = set(_INLINE_MARK) | {"a", "br", "span", "font", "sub", "sup"}


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs=None):
        self.tag = tag
        self.attrs: Dict[str, str] = {k: (v or "") for k, v in (attrs or [])}
        self.children: List[Any] = []  # _Node | str


class _DOMBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), attrs)
        self.stack[-1].children.append(node)
        if tag.lower() not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _build_dom(html: str) -> _Node:
    b = _DOMBuilder()
    b.feed(html or "")
    b.close()
    return b.root


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _rows(table: _Node) -> List[_Node]:
    """All <tr> under a table, descending through thead/tbody/tfoot."""
    out: List[_Node] = []

    def walk(n: _Node):
        for c in n.children:
            if isinstance(c, _Node):
                if c.tag == "tr":
                    out.append(c)
                elif c.tag in ("thead", "tbody", "tfoot"):
                    walk(c)
    walk(table)
    return out


def _cells(row: _Node) -> List[_Node]:
    return [c for c in row.children if isinstance(c, _Node) and c.tag in ("th", "td")]


# ---------------------------------------------------------------------------
# HTML -> ADF (Jira Cloud, REST v3)
# ---------------------------------------------------------------------------
def html_to_adf(html: str) -> Dict[str, Any]:
    blocks = _adf_blocks(_build_dom(html))
    if not blocks:
        blocks = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": blocks}


def _adf_inline(node: _Node, marks: List[Dict[str, Any]], out: List[Dict[str, Any]]) -> None:
    for child in node.children:
        if isinstance(child, str):
            text = _norm_ws(child)
            if text:
                n: Dict[str, Any] = {"type": "text", "text": text}
                if marks:
                    n["marks"] = [dict(m) for m in marks]
                out.append(n)
            continue
        tag = child.tag
        if tag == "br":
            out.append({"type": "hardBreak"})
        elif tag == "a":
            href = child.attrs.get("href", "")
            m = marks + ([{"type": "link", "attrs": {"href": href}}] if href else [])
            _adf_inline(child, m, out)
        elif tag in _INLINE_MARK:
            _adf_inline(child, marks + [{"type": _INLINE_MARK[tag]}], out)
        else:
            _adf_inline(child, marks, out)


def _trim_inline(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = list(nodes)
    while out and out[0].get("type") == "text" and not out[0]["text"].strip():
        out.pop(0)
    while out and out[-1].get("type") == "text" and not out[-1]["text"].strip():
        out.pop()
    if out and out[0].get("type") == "text":
        out[0]["text"] = out[0]["text"].lstrip()
    if out and out[-1].get("type") == "text":
        out[-1]["text"] = out[-1]["text"].rstrip()
    return [n for n in out if n.get("type") != "text" or n["text"]]


def _adf_paragraph(inline: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    trimmed = _trim_inline(inline)
    return {"type": "paragraph", "content": trimmed} if trimmed else None


def _adf_cell_content(cell: _Node) -> List[Dict[str, Any]]:
    blocks = _adf_blocks(cell)
    return blocks or [{"type": "paragraph", "content": []}]


def _adf_table(table: _Node) -> Optional[Dict[str, Any]]:
    rows_out: List[Dict[str, Any]] = []
    for tr in _rows(table):
        cells_out: List[Dict[str, Any]] = []
        for cell in _cells(tr):
            attrs: Dict[str, Any] = {}
            for src, dst in (("colspan", "colspan"), ("rowspan", "rowspan")):
                try:
                    v = int(cell.attrs.get(src, "1"))
                    if v > 1:
                        attrs[dst] = v
                except ValueError:
                    pass
            cells_out.append({
                "type": "tableHeader" if cell.tag == "th" else "tableCell",
                "attrs": attrs,
                "content": _adf_cell_content(cell),
            })
        if cells_out:
            rows_out.append({"type": "tableRow", "content": cells_out})
    if not rows_out:
        return None
    return {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": rows_out}


def _adf_list(node: _Node, ordered: bool) -> Optional[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for li in [c for c in node.children if isinstance(c, _Node) and c.tag == "li"]:
        content = _adf_blocks(li) or [{"type": "paragraph", "content": []}]
        items.append({"type": "listItem", "content": content})
    if not items:
        return None
    return {"type": "orderedList" if ordered else "bulletList", "content": items}


def _adf_blocks(node: _Node) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    inline: List[Dict[str, Any]] = []

    def flush():
        nonlocal inline
        if inline:
            p = _adf_paragraph(inline)
            if p:
                result.append(p)
            inline = []

    for child in node.children:
        if isinstance(child, str):
            if child.strip() or inline:
                _adf_inline(_wrap(child), [], inline)
            continue
        tag = child.tag
        if tag in _INLINE_TAGS:
            _adf_inline(_wrap_node(child), [], inline)
        elif tag in ("p", "div", "section", "article"):
            flush()
            result.extend(_adf_blocks(child))
        elif tag in _HEADINGS:
            flush()
            para = _adf_paragraph(_inline_of(child))
            level = int(tag[1])
            result.append({"type": "heading", "attrs": {"level": min(max(level, 1), 6)},
                           "content": para["content"] if para else []})
        elif tag == "table":
            flush()
            t = _adf_table(child)
            if t:
                result.append(t)
        elif tag in ("ul", "ol"):
            flush()
            lst = _adf_list(child, ordered=(tag == "ol"))
            if lst:
                result.append(lst)
        elif tag == "blockquote":
            flush()
            inner = _adf_blocks(child) or [{"type": "paragraph", "content": []}]
            result.append({"type": "blockquote", "content": inner})
        elif tag == "hr":
            flush()
            result.append({"type": "rule"})
        elif tag in ("pre",):
            flush()
            text = _text_of(child)
            result.append({"type": "codeBlock", "content": [{"type": "text", "text": text}] if text else []})
        else:
            inner = _adf_blocks(child)
            if inner:
                flush()
                result.extend(inner)
    flush()
    return result


def _wrap(text: str) -> _Node:
    n = _Node("span")
    n.children = [text]
    return n


def _wrap_node(node: _Node) -> _Node:
    n = _Node("span")
    n.children = [node]
    return n


def _inline_of(node: _Node) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    _adf_inline(node, [], out)
    return out


# ---------------------------------------------------------------------------
# HTML -> Jira wiki markup (Server / Data Center, REST v2)
# ---------------------------------------------------------------------------
def html_to_wiki(html: str) -> str:
    blocks = _wiki_blocks(_build_dom(html))
    return "\n\n".join(b for b in blocks if b.strip()).strip()


def _wiki_inline(node: _Node) -> str:
    parts: List[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(_norm_ws(child))
            continue
        tag = child.tag
        inner = _wiki_inline(child)
        if tag == "br":
            parts.append("\n")
        elif tag in ("strong", "b"):
            parts.append(f"*{inner}*" if inner.strip() else inner)
        elif tag in ("em", "i"):
            parts.append(f"_{inner}_" if inner.strip() else inner)
        elif tag == "code":
            parts.append(f"{{{{{inner}}}}}")
        elif tag in ("s", "strike", "del"):
            parts.append(f"-{inner}-" if inner.strip() else inner)
        elif tag == "a":
            href = child.attrs.get("href", "")
            parts.append(f"[{inner}|{href}]" if href else inner)
        else:
            parts.append(inner)
    return "".join(parts)


def _wiki_cell(cell: _Node) -> str:
    # Table cells must stay on one line; wiki uses \\ for an in-cell line break.
    text = _wiki_inline(cell).strip()
    return text.replace("\n", " \\\\ ") or " "


def _wiki_table(table: _Node) -> str:
    lines: List[str] = []
    for tr in _rows(table):
        cells = _cells(tr)
        if not cells:
            continue
        if all(c.tag == "th" for c in cells):
            lines.append("||" + "||".join(_wiki_cell(c) for c in cells) + "||")
        else:
            lines.append("|" + "|".join(_wiki_cell(c) for c in cells) + "|")
    return "\n".join(lines)


def _wiki_blocks(node: _Node) -> List[str]:
    result: List[str] = []
    inline_parts: List[str] = []

    def flush():
        nonlocal inline_parts
        text = "".join(inline_parts).strip()
        if text:
            result.append(text)
        inline_parts = []

    for child in node.children:
        if isinstance(child, str):
            if child.strip() or inline_parts:
                inline_parts.append(_norm_ws(child))
            continue
        tag = child.tag
        if tag in _INLINE_TAGS:
            inline_parts.append(_wiki_inline(_wrap_node(child)))
        elif tag in ("p", "div", "section", "article"):
            flush()
            result.extend(_wiki_blocks(child))
        elif tag in _HEADINGS:
            flush()
            result.append(f"h{tag[1]}. {_wiki_inline(child).strip()}")
        elif tag == "table":
            flush()
            t = _wiki_table(child)
            if t:
                result.append(t)
        elif tag in ("ul", "ol"):
            flush()
            bullet = "#" if tag == "ol" else "*"
            for li in [c for c in child.children if isinstance(c, _Node) and c.tag == "li"]:
                result.append(f"{bullet} {_wiki_inline(li).strip()}")
        elif tag == "blockquote":
            flush()
            result.append("bq. " + _wiki_inline(child).strip())
        elif tag == "hr":
            flush()
            result.append("----")
        elif tag == "pre":
            flush()
            result.append("{code}\n" + _text_of(child) + "\n{code}")
        else:
            inner = _wiki_blocks(child)
            if inner:
                flush()
                result.extend(inner)
    flush()
    return result


def _text_of(node: _Node) -> str:
    out: List[str] = []

    def walk(n: _Node):
        for c in n.children:
            if isinstance(c, str):
                out.append(c)
            else:
                walk(c)
    walk(node)
    return "".join(out).strip()


def count_tables(html: str) -> int:
    dom = _build_dom(html)
    n = 0

    def walk(node: _Node):
        nonlocal n
        for c in node.children:
            if isinstance(c, _Node):
                if c.tag == "table":
                    n += 1
                walk(c)
    walk(dom)
    return n

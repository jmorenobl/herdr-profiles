"""Changing a JSON file of the person's own (keys.json, profiles.json) with the smallest textual edit.

`update(text, new)` returns `text` changed so it parses to `new`: members and array items that
are added go after the last one, written in the file's own style (its indentation, inline or one
per line); those removed are cut out with their comma; a changed value is rewritten in place.
Everything else (spacing, key order, escapes, the final newline) stays byte for byte.

What isn't kept: a value that changes is rewritten whole in the file's style (an array is
appended to or cut from only when the change is just that); new members go last, whatever order
`new` has them in; the space inside an empty object or array ("{ }") once filled and emptied
again (it comes back as "{}"); and a file with duplicate keys, or any edit that wouldn't parse back to
`new`, is written whole instead, with the file's indentation (`rewrite`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

WS = " \t\n\r"  # JSON's whitespace, the same json.loads skips
DECODER = json.JSONDecoder()


@dataclass
class Node:
    start: int
    end: int
    kind: str  # "object", "array" or "value"
    value: Any = None
    # object: [(key, key start, value node)]; array: [(None, item start, item node)]
    members: list = field(default_factory=list)
    open: int = 0  # the position just after "{" or "["


def same(a: Any, b: Any) -> bool:
    """Equal as JSON (True isn't 1 here); key order doesn't count."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in WS:
        i += 1
    return i


def parse(text: str, i: int = 0) -> Node:
    """The value at `i` (after whitespace), with where each part is. ValueError if it isn't JSON."""
    i = skip(text, i)
    if i >= len(text):
        raise ValueError("unexpected end")
    c = text[i]
    if c in "{[":
        close = "}" if c == "{" else "]"
        node = Node(i, i, "object" if c == "{" else "array", open=i + 1)
        j = skip(text, i + 1)
        if j < len(text) and text[j] == close:
            node.end = j + 1
            node.value = {} if c == "{" else []
            return node
        while True:
            j = skip(text, j)
            if c == "{":
                if j >= len(text) or text[j] != '"':
                    raise ValueError(f"expected a key at {j}")
                key, after = DECODER.raw_decode(text, j)
                k = skip(text, after)
                if k >= len(text) or text[k] != ":":
                    raise ValueError(f"expected ':' at {k}")
                child = parse(text, k + 1)
                node.members.append((key, j, child))
            else:
                child = parse(text, j)
                node.members.append((None, child.start, child))
            j = skip(text, child.end)
            if j < len(text) and text[j] == ",":
                j += 1
                continue
            if j < len(text) and text[j] == close:
                node.end = j + 1
                break
            raise ValueError(f"expected ',' or '{close}' at {j}")
        if c == "{":
            node.value = {k: m.value for k, _, m in node.members}
        else:
            node.value = [m.value for _, _, m in node.members]
        return node
    value, end = DECODER.raw_decode(text, i)
    return Node(i, end, "value", value)


def unit(text: str) -> str | None:
    """The file's indentation step ("  ", "\t", …), or None when it's all on one line."""
    widths = [m.group(1) for m in re.finditer(r"\n([ \t]+)\S", text)]
    if not widths:
        return None if "\n" not in text.strip(WS) else "  "
    if any(w.startswith("\t") for w in widths):
        return "\t"
    return " " * min(len(w) for w in widths)


def line_indent(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = start
    while end < len(text) and text[end] in " \t":
        end += 1
    return text[start:end]


def compact(text: str) -> bool:
    """True when the file writes ":" and "," with no space after them."""
    return re.search(r'":\s', text) is None and re.search(r'":\S', text) is not None


def render(value: Any, text: str, indent: str | None) -> str:
    """`value` as the file would write it: one per line from `indent` on, or inline (indent None)."""
    step = unit(text)
    if indent is None or step is None or not (isinstance(value, (dict, list)) and value):
        if compact(text):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, ensure_ascii=False)
    out = json.dumps(value, ensure_ascii=False, indent=step)
    return out.replace("\n", "\n" + indent)


def member(key: str | None, value: Any, text: str, indent: str | None) -> str:
    body = render(value, text, indent)
    if key is None:
        return body
    colon = ":" if compact(text) else ": "
    return json.dumps(key, ensure_ascii=False) + colon + body


def gap(text: str, node: Node, index: int) -> str:
    """The whitespace before member `index`, after the "{" or "," before it."""
    start = node.members[index][1]
    j = start
    while j > 0 and text[j - 1] in WS:
        j -= 1
    return text[j:start]


def one_edit(text: str, node: Node, new: Any) -> tuple[int, int, str] | None:
    """The first edit that takes `node` towards `new`, or None when it's there already."""
    if same(node.value, new):
        return None
    if node.kind == "object" and isinstance(new, dict):
        keys = [k for k, _, _ in node.members]
        if len(set(keys)) != len(keys):
            return replace(text, node, new)
        for index, (key, _, child) in enumerate(node.members):
            if key not in new:
                return cut(text, node, index)
        for key, _, child in node.members:
            edit = one_edit(text, child, new[key])
            if edit is not None:
                return edit
        for key, value in new.items():
            if key not in node.value:
                return add(text, node, key, value)
        return None
    if node.kind == "array" and isinstance(new, list):
        old = node.value
        if same(old, new[:len(old)]):
            return add(text, node, None, new[len(old)])
        if len(new) < len(old) and is_removal(old, new):
            j = 0  # cut the first item that isn't in `new`, matching the rest in order
            for index, item in enumerate(old):
                if j < len(new) and same(item, new[j]):
                    j += 1
                else:
                    return cut(text, node, index)
        return replace(text, node, new)
    return replace(text, node, new)


def is_removal(old: list, new: list) -> bool:
    j = 0
    for item in old:
        if j < len(new) and same(item, new[j]):
            j += 1
    return j == len(new)


def replace(text: str, node: Node, new: Any) -> tuple[int, int, str]:
    # One per line where the file is: a value that spanned lines, or a plain value now a list or object.
    multiline = unit(text) is not None and ("\n" in text[node.start:node.end] or node.kind == "value")
    return node.start, node.end, render(new, text, line_indent(text, node.start) if multiline else None)


def cut(text: str, node: Node, index: int) -> tuple[int, int, str]:
    members = node.members
    if len(members) == 1:
        return node.open, node.end - 1, ""
    if index < len(members) - 1:
        return members[index][1], members[index + 1][1], ""
    return members[index - 1][2].end, members[index][2].end, ""


def add(text: str, node: Node, key: str | None, value: Any) -> tuple[int, int, str]:
    if not node.members:
        if unit(text) is None:
            return node.open, node.end - 1, member(key, value, text, None)
        outer = line_indent(text, node.start)
        inner = outer + unit(text)
        return node.open, node.end - 1, f"\n{inner}{member(key, value, text, inner)}\n{outer}"
    last = node.members[-1][2]
    sep = gap(text, node, len(node.members) - 1)
    if "\n" not in sep and len(node.members) == 1:
        sep = "" if compact(text) else " "  # the only gap seen is the one after "{" or "["
    indent = sep.rsplit("\n", 1)[1] if "\n" in sep else None
    if last.kind != "value" and "\n" not in text[last.start:last.end]:
        indent = None  # its siblings are written inline: so is it
    at = last.end
    return at, at, "," + sep + member(key, value, text, indent)


def update(text: str, new: Any) -> str:
    """`text` with the smallest edits that make it parse to `new` (see the module's docstring)."""
    try:
        for _ in range(10000):
            root = parse(text)
            if skip(text, root.end) != len(text):
                raise ValueError("text after the value")
            edit = one_edit(text, root, new)
            if edit is None:
                break
            start, end, repl = edit
            text = text[:start] + repl + text[end:]
        else:
            raise ValueError("too many edits")
        if same(json.loads(text), new):
            return text
    except ValueError:
        pass
    return rewrite(text, new)


def rewrite(text: str, new: Any) -> str:
    """`new` written whole, with the file's indentation and final newline where they can be told."""
    step = unit(text) if text.strip(WS) else "  "
    out = json.dumps(new, ensure_ascii=False, indent=step) if step else json.dumps(new, ensure_ascii=False)
    return out + ("\n" if text.endswith("\n") or not text else "")

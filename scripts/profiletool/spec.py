"""profile.json: what a package is, checked before anything is built or installed.

A package is a folder with a profile.json and, optionally, layouts/, themes/ and
mods/ laid out like the Herdr home. Schema 2 (current):

  {
    "schema": 2,
    "name": "ideas",                      lowercase, digits and dashes
    "description": "...",
    "default": true,                      optional: the default profile
    "layout": {
      "name": "ideas",                    installed as layouts/<name>.json
      "source": "layouts/x.json"          a layout file in this package, or
      "base": "standard",                 another package's layout (by layout name)
      "insert": [{ "into": "<node id>", "after": "<child id>", "node": {...} }],
      "set": { "theme": "ideas" }         keys set on the root node (not inherited
    },                                    by layouts built on this one)
    "settings": {...},                    first-time entry in profiles.json
    "ask": [{ "setting": "folder",        asked the first time the profile is added
              "question": "Where...?",    to profiles.json (Enter takes the default;
              "default": "~/ideas",       no terminal: the default, said in the output)
              "kind": "folder" }],        optional: "text" (default) or "folder"
    "rules": [{ "path": "~/x" } | { "has": ".marker" }],
    "keys": { "<section>": { "<key>": "<action>" } }
  }

The answer to an `ask` goes into the profile's settings under its `setting`
name, and a rule's string values can use it as `{setting}` (for example
`{ "path": "{folder}" }`), so the suggested rule follows the answer. A
placeholder must name an `ask` setting; an `ask` setting can't also be in
`settings`.

Every answer is one line with no control characters. A "folder" answer
starts with "/" or "~/", has no "." or ".." parts, and isn't "/", "~" or the
home folder or a folder above it (a rule there would match every project),
and has no "//". Surrounding whitespace is dropped. The default must pass
too (in profile.json, and again against the real home at install).

Schema 1 (a "layout" string naming layouts/<name>.json) is still read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .files import load_json

SCHEMA = 2
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TOP_KEYS = {"schema", "name", "description", "default", "layout", "settings", "ask", "rules", "keys"}
ASK_KEYS = {"setting", "question", "default"}
ASK_KINDS = ("text", "folder")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SETTING = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
LAYOUT_KEYS = {"name", "source", "base", "insert", "set"}
INSERT_KEYS = {"into", "after", "before", "node"}


class SpecError(Exception):
    """A profile.json that can't be used; the message says where and why."""


@dataclass(frozen=True)
class Insert:
    into: str                 # id of the node whose children get the new node
    node: dict[str, Any]
    after: str | None = None  # id of the sibling it goes after (or before); neither: last
    before: str | None = None


@dataclass(frozen=True)
class LayoutRecipe:
    name: str
    source: str | None = None  # path inside the package
    base: str | None = None    # another package's layout name
    inserts: tuple[Insert, ...] = ()
    set: dict[str, Any] = field(default_factory=dict)

    @property
    def derived(self) -> bool:
        return self.base is not None

    @property
    def plain(self) -> bool:
        """Only a source file plus the switcher: what Herdr shows can be pulled back."""
        return self.source is not None and not self.inserts and not self.set


@dataclass(frozen=True)
class Ask:
    setting: str    # the key it sets in the profile's settings, and its {placeholder} in rules
    question: str
    default: str
    kind: str = "text"

    def check(self, value: str, home: Path | None = None) -> tuple[str, str | None]:
        """(the answer as it will be stored, None) or (value, why it can't be used)."""
        value = value.strip()
        if not value:
            return value, "it can't be empty"
        if CONTROL.search(value):
            return value, "it can't contain control characters (tabs, newlines, …)"
        if self.kind == "folder":
            return check_folder(value, home or Path.home())
        return value, None


def check_folder(value: str, home: Path) -> tuple[str, str | None]:
    """A folder rules can match: absolute or ~/, not the root, the home folder or above it.
    The mod's config.js checkFolder is the same rule; keep them in step."""
    if value != "/" and value.endswith("/"):
        value = value.rstrip("/") or "/"
    if value in ("/", "~"):
        return value, "it can't be / or your home folder: a rule there would match every project"
    if not (value.startswith("/") or value.startswith("~/")):
        return value, "it must be a folder starting with / or ~/"
    if "//" in value:
        return value, "it can't have // in it"
    if any(part in (".", "..") for part in value.split("/")):
        return value, "it can't have . or .. in it"
    full = value.replace("~", str(home).rstrip("/"), 1) if value.startswith("~") else value
    home_s = str(home).rstrip("/") or "/"
    if full == home_s or home_s.startswith(full + "/"):
        return value, "it can't be / or your home folder, or a folder above it: a rule there would match every project"
    return value, None


@dataclass(frozen=True)
class Package:
    path: Path
    name: str
    layout: LayoutRecipe
    default: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    rules: tuple[dict[str, Any], ...] = ()
    keys: dict[str, dict[str, str]] = field(default_factory=dict)
    ask: tuple[Ask, ...] = ()

    def __str__(self) -> str:
        return self.name


def folders(repo: Path) -> list[Path]:
    """core/ first, then profiles/<name>/ in name order."""
    return [repo / "core", *sorted(p for p in (repo / "profiles").glob("*") if p.is_dir())]


def strays(repo: Path) -> list[Path]:
    """Folders under profiles/ without a profile.json (a leftover, or work in progress)."""
    return [f for f in folders(repo)[1:] if not (f / "profile.json").exists()]


def discover(repo: Path) -> list[Package]:
    """Every package, valid or an error. Folders without a profile.json are left out (see strays)."""
    packages = [load(folder) for folder in folders(repo) if folder not in strays(repo)]
    seen: dict[str, Package] = {}
    for pkg in packages:
        for key, value in (("profile", pkg.name), ("layout", pkg.layout.name)):
            other = seen.get(f"{key}:{value}")
            if other:
                raise SpecError(f"{pkg.path}: {key} name {value!r} is also used by {other.path}")
            seen[f"{key}:{value}"] = pkg
    return packages


def load(folder: Path) -> Package:
    path = folder / "profile.json"
    if not path.is_file():
        raise SpecError(f"{folder}: missing profile.json")
    try:
        data = load_json(path, None)
    except ValueError as err:
        raise SpecError(f"{path}: invalid JSON: {err}") from None
    return parse(data, folder)


def parse(data: Any, folder: Path) -> Package:
    where = folder / "profile.json"

    def fail(msg: str) -> SpecError:
        return SpecError(f"{where}: {msg}")

    if not isinstance(data, dict):
        raise fail("must be a JSON object")
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise fail(f"unknown keys {sorted(unknown)}")
    schema = data.get("schema", 1)
    if schema not in (1, SCHEMA):
        raise fail(f"schema {schema!r} is not supported (this tool reads 1 and {SCHEMA})")
    name = data.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise fail("'name' must be lowercase letters, digits and dashes")

    layout = data.get("layout")
    if isinstance(layout, str):  # schema 1
        layout = {"name": layout, "source": f"layouts/{layout}.json"}
    if not isinstance(layout, dict):
        raise fail("'layout' must be an object (or, in schema 1, a name)")
    recipe = parse_layout(layout, folder, fail)

    settings = data.get("settings", {})
    if not isinstance(settings, dict) or "layout" in settings:
        raise fail("'settings' must be an object without 'layout'")
    rules = data.get("rules", [])
    if not isinstance(rules, list) or not all(
        isinstance(r, dict) and (r.get("path") or r.get("has")) and "profile" not in r for r in rules
    ):
        raise fail("'rules' must be a list of objects with 'path' and/or 'has' (the profile is implied)")
    ask = parse_ask(data.get("ask", []), settings, fail)
    asked = {a.setting for a in ask}
    for n, rule in enumerate(rules):
        for value in rule.values():
            for ref in PLACEHOLDER.findall(value) if isinstance(value, str) else ():
                if ref not in asked:
                    raise fail(f"'rules[{n}]' uses {{{ref}}}, which no 'ask' sets")
    keys = data.get("keys", {})
    if not isinstance(keys, dict) or not all(
        isinstance(b, dict) and all(isinstance(k, str) and isinstance(a, str) for k, a in b.items())
        for b in keys.values()
    ):
        raise fail("'keys' must map sections to {key: action}")
    if not isinstance(data.get("default", False), bool):
        raise fail("'default' must be true or false")
    return Package(folder, name, recipe, data.get("default", False), settings, tuple(rules), keys, ask)


def parse_ask(ask: Any, settings: dict[str, Any], fail) -> tuple[Ask, ...]:
    if not isinstance(ask, list):
        raise fail("'ask' must be a list of {setting, question, default}")
    out: list[Ask] = []
    for n, item in enumerate(ask):
        if not isinstance(item, dict) or not ASK_KEYS <= set(item) <= ASK_KEYS | {"kind"}:
            raise fail(f"'ask[{n}]' needs exactly {sorted(ASK_KEYS)}, and optionally 'kind'")
        kind = item.get("kind", "text")
        if kind not in ASK_KINDS:
            raise fail(f"'ask[{n}].kind' must be one of {list(ASK_KINDS)}")
        setting, question, default = item["setting"], item["question"], item["default"]
        if not isinstance(setting, str) or not SETTING.match(setting) or setting == "layout":
            raise fail(f"'ask[{n}].setting' must be a setting name (letters, digits, _), not 'layout'")
        if setting in settings:
            raise fail(f"'ask[{n}].setting' {setting!r} is also in 'settings': keep it in one place")
        if any(a.setting == setting for a in out):
            raise fail(f"'ask[{n}].setting' {setting!r} is asked twice")
        if not isinstance(question, str) or not question.strip():
            raise fail(f"'ask[{n}].question' must be a non-empty string")
        if not isinstance(default, str) or not default.strip():
            raise fail(f"'ask[{n}].default' must be a non-empty string")
        ask = Ask(setting, question.strip(), default.strip(), kind)
        default, problem = ask.check(default, Path("/nonexistent-home"))
        if problem:
            raise fail(f"'ask[{n}].default' {item['default']!r}: {problem}")
        out.append(Ask(setting, ask.question, default, kind))
    return tuple(out)


def parse_layout(layout: dict[str, Any], folder: Path, fail) -> LayoutRecipe:
    unknown = set(layout) - LAYOUT_KEYS
    if unknown:
        raise fail(f"unknown keys in 'layout': {sorted(unknown)}")
    name = layout.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise fail("'layout.name' must be lowercase letters, digits and dashes")
    source, base = layout.get("source"), layout.get("base")
    if (source is None) == (base is None):
        raise fail("'layout' needs exactly one of 'source' (a file here) or 'base' (another layout)")
    if source is not None and not (isinstance(source, str) and (folder / source).is_file()):
        raise fail(f"'layout.source' {source!r} is not a file in the package")
    if base is not None and not isinstance(base, str):
        raise fail("'layout.base' must be a layout name")
    inserts = []
    for n, item in enumerate(layout.get("insert", [])):
        if not isinstance(item, dict) or set(item) - INSERT_KEYS:
            raise fail(f"'layout.insert[{n}]' takes only {sorted(INSERT_KEYS)}")
        if not isinstance(item.get("into"), str) or not isinstance(item.get("node"), dict):
            raise fail(f"'layout.insert[{n}]' needs 'into' (a node id) and 'node' (an object)")
        if not isinstance(item["node"].get("id"), str):
            raise fail(f"'layout.insert[{n}].node' needs an 'id'")
        if item.get("after") is not None and item.get("before") is not None:
            raise fail(f"'layout.insert[{n}]' takes 'after' or 'before', not both")
        inserts.append(Insert(item["into"], item["node"], item.get("after"), item.get("before")))
    to_set = layout.get("set", {})
    if not isinstance(to_set, dict) or {"id", "type", "children", "floating"} & set(to_set):
        raise fail("'layout.set' must be an object and can't replace id, type, children or floating")
    return LayoutRecipe(name, source, base, tuple(inserts), to_set)

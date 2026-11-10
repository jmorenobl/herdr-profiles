"""The person's own files: profiles.json (which project gets which profile) and keys.json.

They belong to the person, never to this repo. The first time a profile is
installed, its entry, suggested rules and keys are added once; after that the
tool never changes them, even if the person removed what it added.

A profile can ask for settings (its `ask`) that first time: on a terminal the
person answers (Enter takes the default; an answer that can't be used is
explained and asked again), `install --set <profile>.<setting>=<value>`
answers in advance, and without a terminal the default is used and said.
A profile already installed, or already in profiles.json, is never asked again.

Install reads and checks both files, asks, and works out the whole merge
before it writes anything (`plan_first_time`), then writes it last
(`Merge.apply`): a broken file or a stop at a question leaves the home as it was.

Both files are changed with the smallest textual edit (jsonedit): the person's formatting stays,
and an uninstall that takes back all an install added leaves the file as it was (but an empty
object with space inside, "{ }" or on several lines, which comes back as "{}"). The top-level keys install
added to profiles.json ("config_keys") go again on uninstall once they're empty.

What it added is recorded in the manifest ("added", see manifest.py), exactly
as added; for a profile installed before 0.8.0, what is still exactly as it
would have been added is recognised and recorded by the next install
(`recognise_old`). Uninstall (`plan_removal`) takes back only what is still exactly
that: an entry, rule or key the person changed, or added themselves, stays.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import jsonedit
from pathlib import Path

from .files import atomic_write, dump_json, load_json, notify
from .home import Home
from .spec import PLACEHOLDER, Package, SpecError

Prompt = Optional[Callable[[str], str]]  # input() on a terminal; None without one


def empty_config() -> dict:
    return {"default": None, "profiles": {}, "rules": []}


def load_config(home: Home) -> dict:
    """profiles.json, checked enough to merge into; a SpecError says what's wrong."""
    where = home.profiles_path
    try:
        config = load_json(where, empty_config())
    except (ValueError, OSError) as err:
        raise SpecError(f"{where}: can't read it ({err}); fix it, or move it away to start over") from None
    if not isinstance(config, dict):
        raise SpecError(f"{where}: must be a JSON object")
    config.setdefault("profiles", {})
    config.setdefault("rules", [])
    if not isinstance(config["profiles"], dict):
        raise SpecError(f"{where}: 'profiles' must be an object")
    if not isinstance(config["rules"], list):
        raise SpecError(f"{where}: 'rules' must be a list")
    return config


def load_keys(home: Home) -> dict | None:
    """keys.json, or None when there isn't one; a SpecError says what's wrong."""
    where = home.keys_path
    try:
        keys = load_json(where, None)
    except (ValueError, OSError) as err:
        raise SpecError(f"{where}: can't read it ({err})") from None
    if keys is not None and not (isinstance(keys, dict) and all(isinstance(v, dict) for v in keys.values())):
        raise SpecError(f"{where}: must map sections to {{key: action}}")
    return keys


def parse_sets(sets: list[str], packages: list[Package]) -> dict[str, dict[str, str]]:
    """`--set ideas.folder=~/notes` -> {"ideas": {"folder": "~/notes"}}, checked against the asks.
    The values are checked later (ask_first_time), only for profiles that will use them."""
    out: dict[str, dict[str, str]] = {}
    asks = {(p.name, a.setting): a for p in packages for a in p.ask}
    for item in sets:
        key, eq, value = item.partition("=")
        name, dot, setting = key.partition(".")
        if not eq or not dot or not value.strip():
            raise SpecError(f"--set {item!r}: write it as <profile>.<setting>=<value>")
        ask = asks.get((name, setting))
        if ask is None:
            known = ", ".join(f"{p}.{s}" for p, s in sorted(asks)) or "none"
            raise SpecError(f"--set {item!r}: no profile asks for that (settings you can set: {known})")
        out.setdefault(name, {})[setting] = value
    return out


def known_as(name: str, config: dict, manifest: dict) -> str | None:
    """Why a profile counts as known (never asked again), or None."""
    if name in config["profiles"]:
        return "it's already in profiles.json"
    if name in manifest.get("profiles", []):
        return "it was installed before (removed from profiles.json since)"
    return None


def ask_first_time(packages: list[Package], home: Home, manifest: dict,
                   preset: dict[str, dict[str, str]], prompt: Prompt,
                   config: dict | None = None) -> dict[str, dict[str, str]]:
    """The answers for profiles that are new to this home. Runs before install writes anything."""
    config = load_config(home) if config is None else config
    answers: dict[str, dict[str, str]] = {}
    for pkg in packages:
        given = preset.get(pkg.name, {})
        known = known_as(pkg.name, config, manifest)
        if known:
            for setting in given:
                print(f"  note      --set {pkg.name}.{setting} ignored: {known}; change it in profiles.json")
            continue
        for ask in pkg.ask:
            if ask.setting in given:
                value, problem = ask.check(given[ask.setting])
                if problem:
                    raise SpecError(f"--set {pkg.name}.{ask.setting}={given[ask.setting]}: {problem}")
                answers.setdefault(pkg.name, {})[ask.setting] = value
                continue
            _, problem = ask.check(ask.default)
            if problem:  # checked in profile.json too, but against no real home
                raise SpecError(f"{pkg.name}: the default for {ask.setting!r} ({ask.default}) can't be used here: {problem}."
                                f" Give one with --set {pkg.name}.{ask.setting}=...")
            if prompt is None:
                value = ask.default
                print(f"  setting   {pkg.name}.{ask.setting} = {value} (the default: no terminal to ask;"
                      f" change it in profiles.json, or install with --set {pkg.name}.{ask.setting}=...)")
            else:
                value = ask_until_valid(pkg, ask, prompt)
            answers.setdefault(pkg.name, {})[ask.setting] = value
    return answers


def ask_until_valid(pkg: Package, ask, prompt: Callable[[str], str]) -> str:
    while True:
        try:
            typed = prompt(f"  {pkg.name}: {ask.question} [{ask.default}] ")
        except EOFError:
            print()
            return ask.default
        value, problem = ask.check(typed.strip() or ask.default)
        if not problem:
            return value
        print(f"  {value!r} won't do: {problem}. Try again (Enter takes {ask.default}).")


def fill(rule: dict, values: dict[str, str]) -> dict:
    """A rule with its {setting} placeholders replaced by the answers."""
    return {k: PLACEHOLDER.sub(lambda m: values[m.group(1)], v) if isinstance(v, str) else v for k, v in rule.items()}


TOP = ("default", "profiles", "rules")  # what install may add to profiles.json at the top


def read_text(path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")  # not read_text: "\r\n" stays as it is
    except FileNotFoundError:
        return None


@dataclass
class Merge:
    """What install will write into the person's files, worked out before any file is written."""
    home: Home
    config: dict
    keys: dict | None
    config_changed: bool = False
    keys_changed: bool = False
    lines: list[str] = field(default_factory=list)
    delete_config: bool = False  # uninstall: profiles.json was created by install and is empty again
    texts: dict = field(default_factory=dict)  # each file's text as read: what the edits start from

    def __post_init__(self):
        for path in (self.home.profiles_path, self.home.keys_path):
            self.texts.setdefault(path.name, read_text(path))

    def planned(self) -> dict[str, bytes | None]:
        """{"profiles.json" | "keys.json": the bytes `apply` will write, or None: it deletes it},
        for each file it changes. The person's own formatting is kept (jsonedit)."""
        out: dict[str, bytes | None] = {}
        if self.delete_config:
            out[self.home.profiles_path.name] = None
        elif self.config_changed:
            out[self.home.profiles_path.name] = self.text(self.home.profiles_path.name, self.config)
        if self.keys_changed:
            out[self.home.keys_path.name] = self.text(self.home.keys_path.name, self.keys)
        return out

    def text(self, name: str, data: Any) -> bytes:
        before = self.texts.get(name)
        return dump_json(data) if before is None else jsonedit.update(before, data).encode()

    def apply(self, planned: dict[str, bytes | None] | None = None,
              done: Callable[[str], None] | None = None) -> int:
        """Writes the files and prints what changed; `done(name)` after each one (the journal).
        Returns how many files changed (0-2)."""
        for line in self.lines:
            print(line)
        planned = self.planned() if planned is None else planned
        for name, data in planned.items():
            put(self.home.file(name), data)
            if done:
                done(name)
        return int(self.config_changed) + int(self.keys_changed)


def put(path: Path, data: bytes | None) -> None:
    """Writes a personal file (None: deletes it). Through a symlink, both times: the person's link
    stays, and what changes is the file behind it."""
    if data is None:
        target = Path(os.path.realpath(path))
        target.unlink(missing_ok=True)
        notify("delete", target)
    else:
        atomic_write(path, data)


def plan_first_time(packages: list[Package], home: Home, manifest: dict,
                    answers: dict[str, dict[str, str]] | None = None,
                    config: dict | None = None, keys: Any = ...) -> Merge:
    """Adds what each never-seen profile suggests, with the answers to its asks, in memory.
    Marks those profiles known in `manifest` (saved by the caller after `apply`)."""
    answers = answers or {}
    config = load_config(home) if config is None else config
    keys = load_keys(home) if keys is ... else keys
    merge = Merge(home, config, keys)
    known: list[str] = manifest.setdefault("profiles", [])
    # "config_keys" is kept from a home's first install on; a manifest from before 0.9.2 never
    # had it, and then it stays unknown (what an older install added isn't known).
    tracked = "config_keys" in manifest or not known
    if not home.profiles_path.exists() and any(p.name not in known for p in packages):
        created = manifest.setdefault("created", [])
        if "profiles.json" not in created:
            created.append("profiles.json")
    raw = merge.texts.get(home.profiles_path.name)
    had = set(json.loads(raw)) if raw is not None else set()  # load_config checked it's an object
    for pkg in packages:
        if pkg.name in known:
            continue
        known.append(pkg.name)
        added = pkg.name not in config["profiles"]
        record = {"entry": None, "rules": [], "keys": [], "default": False}
        manifest.setdefault("added", {})[pkg.name] = record
        if added:
            config["profiles"][pkg.name] = {"layout": pkg.layout.name, **pkg.settings, **answers.get(pkg.name, {})}
            record["entry"] = copy.deepcopy(config["profiles"][pkg.name])
        # Rules follow the profile's own value for each asked setting (the person's, if it was there).
        entry = config["profiles"][pkg.name]
        if not isinstance(entry, dict):
            entry = {}
            merge.lines.append(f"  note      profiles.json: {pkg.name}'s entry isn't an object; left as it is,"
                               " and its suggested rules use the defaults")
        values, unusable = {}, set()
        for a in pkg.ask:
            own = entry.get(a.setting)
            if own is None:
                values[a.setting] = answers.get(pkg.name, {}).get(a.setting, a.default)
                continue
            value, problem = a.check(own) if isinstance(own, str) else (own, "it isn't a string")
            if problem:
                # Their entry stays as it is; rules built from that value would be wrong, so they're left out.
                unusable.add(a.setting)
                merge.lines.append(f"  note      profiles.json: {pkg.name}.{a.setting} = {json.dumps(own)} won't do ({problem});"
                                   " its suggested rules were not added")
            values[a.setting] = value
        if pkg.default and not config.get("default"):
            config["default"] = pkg.name
            record["default"] = True
        for rule in pkg.rules:
            if any(ref in unusable for v in rule.values() if isinstance(v, str) for ref in PLACEHOLDER.findall(v)):
                continue
            rule = {**fill(rule, values), "profile": pkg.name}
            if rule not in config["rules"]:
                config["rules"].append(rule)
                record["rules"].append(copy.deepcopy(rule))
        merge.keys_changed |= merge_keys(pkg, keys, merge.lines, record["keys"])
        merge.config_changed = True
        merge.lines.append(f"  profile   {pkg.name} {'added to' if added else 'already in'} profiles.json")
    if merge.config_changed and tracked:
        top = manifest.setdefault("config_keys", [])
        top.extend(k for k in TOP if k in config and k not in had and k not in top)
    return merge


def merge_first_time(packages: list[Package], home: Home, manifest: dict,
                     answers: dict[str, dict[str, str]] | None = None) -> int:
    """plan_first_time, then apply. Returns how many files changed (0-2)."""
    return plan_first_time(packages, home, manifest, answers).apply()


def merge_keys(pkg: Package, keys: dict | None, lines: list[str], record: list | None = None) -> bool:
    """Adds the profile's keys that are free; never replaces one the person uses.
    A key in a section narrower than `global` (layout:, mod:, terminal) wins over the global one
    there, so a key the person binds globally counts as used too: adding it would hide theirs.
    What it adds goes into `record` (the manifest's "added" keys)."""
    changed = False
    record = [] if record is None else record
    for section, binds in pkg.keys.items():
        if keys is None:
            lines.append(f"  note      no keys.json yet; add {json.dumps(binds)} under {json.dumps(section)} yourself")
            continue
        new_section = section not in keys
        current = keys.get(section, {})
        everywhere = keys.get("global", {}) if section != "global" else {}
        for key, action in binds.items():
            if key not in current and key in everywhere and everywhere[key] != action:
                lines.append(f"  skipped   {key}: bound in global to {everywhere[key]!r}; in {section} it would"
                             f" hide that (wanted {action!r})")
            elif key not in current:
                current = keys.setdefault(section, current)
                current[key] = action
                changed = True
                record.append({"section": section, "key": key, "action": action, "new_section": new_section})
                lines.append(f"  key       {key} -> {action}")
            elif current[key] != action:
                lines.append(f"  skipped   {key}: already bound to {current[key]!r} (wanted {action!r})")
    return changed


def recognise_old(packages: list[Package], manifest: dict, config: dict, keys: dict | None) -> list[str]:
    """For each profile installed before 0.8.0 (known, nothing recorded in "added"): records in
    `manifest`, once, what is still exactly as that install would have added it, so uninstall can
    take it back. Returns the lines that say so. Reads the files; never changes them."""
    lines: list[str] = []
    added = manifest.setdefault("added", {})
    for pkg in packages:
        if pkg.name not in manifest.get("profiles", []) or pkg.name in added:
            continue
        record = recognise(pkg, config, keys)
        added[pkg.name] = record
        found = ([f"profiles.json entry {pkg.name!r}"] if record["entry"] is not None else []) \
            + [f"profiles.json rule {json.dumps(r)}" for r in record["rules"]] \
            + [f"key {k['key']} -> {k['action']}" for k in record["keys"]] \
            + ([f"profiles.json default {pkg.name!r}"] if record["default"] else [])
        if found:
            lines.append(f"  recorded  {pkg.name}: installed by an older version that didn't record what it"
                         " added; these are exactly as it would have added them, so uninstall takes them back:")
            lines.extend(f"              {item}" for item in found)
    return lines


def recognise(pkg: Package, config: dict, keys: dict | None) -> dict:
    """What install would have added for `pkg` that is in the person's files exactly as it would
    have added it, as an "added" record (manifest.py).
    - The entry: only "layout" (the profile's), its fixed settings (the profile's values) and its
      asked settings (any value install would accept: the person's answer), nothing else.
    - Rules: each suggested rule filled with the entry's own answers (none: not recognised).
    - Keys: each of the profile's keys bound to its action (its section is never deleted).
    - The default: the person's default is this profile, and the profile is the default one."""
    record: dict = {"entry": None, "rules": [], "keys": [], "default": False}
    entry = config["profiles"].get(pkg.name)
    values: dict[str, str] = {}
    if isinstance(entry, dict):
        for a in pkg.ask:
            own = entry.get(a.setting)
            if isinstance(own, str) and a.check(own) == (own, None):
                values[a.setting] = own
        shape = {"layout": pkg.layout.name, **pkg.settings, **values}
        if entry == shape and len(values) == len(pkg.ask):
            record["entry"] = copy.deepcopy(entry)
    for rule in pkg.rules:
        refs = [ref for v in rule.values() if isinstance(v, str) for ref in PLACEHOLDER.findall(v)]
        if any(ref not in values for ref in refs):
            continue
        rule = {**fill(rule, values), "profile": pkg.name}
        if rule in config["rules"] and rule not in record["rules"]:
            record["rules"].append(copy.deepcopy(rule))
    for section, binds in pkg.keys.items():
        bound = (keys or {}).get(section)
        for key, action in binds.items():
            if isinstance(bound, dict) and bound.get(key) == action:
                record["keys"].append({"section": section, "key": key, "action": action, "new_section": False})
    record["default"] = bool(pkg.default and config.get("default") == pkg.name)
    return record


MISSING = object()


def plan_removal(names: list[str], home: Home, manifest: dict, packages: list[Package] | None,
                 everything: bool = False) -> Merge:
    """Takes back, in memory, what install added for `names` to profiles.json and keys.json,
    where it's still exactly as install left it; says what it keeps and why. Reads (and checks)
    both files first, so a broken one stops uninstall before anything is removed.
    `everything`: a full uninstall, which may also delete a profiles.json install created."""
    config = load_config(home) if home.profiles_path.exists() else None
    keys = load_keys(home)
    merge = Merge(home, config if config is not None else empty_config(), keys)
    by_name = {p.name: p for p in packages or []}
    for name in names:
        record = manifest.get("added", {}).get(name)
        if record is None:
            unknown_additions(name, by_name.get(name), config, keys, merge.lines)
            continue
        if config is not None:
            take_back_config(name, record, config, merge)
        recorded = {(k["section"], k["key"]) for k in record.get("keys", [])}
        pkg = by_name.get(name)
        for section, binds in (pkg.keys if pkg else {}).items():
            for key, action in binds.items():
                bound = (keys or {}).get(section)
                if (section, key) not in recorded and isinstance(bound, dict) and bound.get(key) == action:
                    merge.lines.append(f"  kept      key {key} -> {action}: install didn't add it (it was"
                                       " there already, or added by an older version)")
        for k in record.get("keys", []):
            section = (keys or {}).get(k["section"])
            now = section.get(k["key"], MISSING) if isinstance(section, dict) else MISSING
            if now is MISSING:
                continue
            if now != k["action"]:
                merge.lines.append(f"  kept      key {k['key']}: now bound to {now!r}, not {k['action']!r} as install left it")
                continue
            del section[k["key"]]
            if not section and k.get("new_section"):
                del keys[k["section"]]
            merge.keys_changed = True
            merge.lines.append(f"  removed   key {k['key']} -> {k['action']}")
    if everything and config is not None:
        drop_empty_tops(config, manifest, merge)
    if not everything and config is not None and config.get("default") in names:
        merge.lines.append(f"  note      profiles.json: \"default\" is still {config['default']!r}, which isn't"
                           " installed now; set it to an installed profile")
    if (everything and config is not None and "profiles.json" in manifest.get("created", [])
            and set(config) <= {"default", "profiles", "rules"} and not config.get("default")
            and not config.get("profiles") and not config.get("rules")):
        merge.delete_config = True
        merge.lines.append("  removed   profiles.json (install created it; nothing is left in it)")
    return merge


def drop_empty_tops(config: dict, manifest: dict, merge: Merge) -> None:
    """On a full uninstall, the top-level keys install added to profiles.json ("config_keys") go
    once empty (null, {} or []), so the person's file is left as they had it. A manifest from before 0.9.2 doesn't say
    which those were: then any of them left empty goes, but only when uninstall changes the file
    anyway (an install before 0.8.0 wrote all three)."""
    known = manifest.get("config_keys")
    if known is None and not merge.config_changed:
        return
    for k in list(TOP if known is None else known):
        if k in config and config[k] in (None, {}, []):
            del config[k]
            merge.config_changed = True
            if known is not None:
                known.remove(k)


def take_back_config(name: str, record: dict, config: dict, merge: Merge) -> None:
    entry = record.get("entry")
    if entry is not None:
        now = config["profiles"].get(name, MISSING)
        if now == entry:
            del config["profiles"][name]
            merge.config_changed = True
            merge.lines.append(f"  removed   profiles.json entry {name!r}")
        elif now is not MISSING:
            merge.lines.append(f"  kept      profiles.json entry {name!r}: changed since install")
    elif name in config["profiles"]:
        merge.lines.append(f"  kept      profiles.json entry {name!r}: install didn't add it (it was there"
                           " already, or added by an older version)")
    for rule in record.get("rules", []):
        if rule in config["rules"]:
            config["rules"].remove(rule)
            merge.config_changed = True
            merge.lines.append(f"  removed   profiles.json rule {json.dumps(rule)}")
    for rule in config["rules"]:
        if rule in record.get("rules", []):
            merge.lines.append(f"  kept      profiles.json rule {json.dumps(rule)}: a second copy of one install"
                               " added (yours, then)")
        elif isinstance(rule, dict) and rule.get("profile") == name:
            merge.lines.append(f"  kept      profiles.json rule {json.dumps(rule)}: not one install added as it is")
    if record.get("default") and config.get("default") == name:
        config["default"] = None
        merge.config_changed = True
        merge.lines.append(f"  removed   profiles.json default {name!r}")


def unknown_additions(name: str, pkg: Package | None, config: dict | None, keys: dict | None,
                      lines: list[str]) -> None:
    """An install that didn't record what it added (before 0.8.0): nothing is taken back.
    Shows what may be from it, for the person to remove if they want."""
    left: list[str] = []
    if config is not None:
        if name in config["profiles"]:
            left.append(f"profiles.json entry {name!r}")
        left += [f"profiles.json rule {json.dumps(r)}" for r in config["rules"]
                 if isinstance(r, dict) and r.get("profile") == name]
        if config.get("default") == name:
            left.append(f"profiles.json default {name!r}")
    for section, binds in (pkg.keys if pkg else {}).items():
        for key, action in binds.items():
            if isinstance((keys or {}).get(section), dict) and keys[section].get(key) == action:
                left.append(f"key {key} -> {action} (keys.json, {section})")
    if left:
        lines.append(f"  kept      what may be from {name} in your own files: it was installed by an older"
                     " version that didn't record what it added, so it's left for you to remove if you want"
                     " (an `install` first records what is exactly as install adds it):")
        lines.extend(f"              {item}" for item in left)

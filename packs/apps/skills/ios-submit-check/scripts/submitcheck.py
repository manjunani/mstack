#!/usr/bin/env python3
"""Find the mechanical reasons an iPhone app upload or review would bounce, before archiving.

  submitcheck.py --project DIR [--screenshots DIR]

Reads, without building anything:
  Info.plist files    every Info.plist under DIR (build folders, Pods, .git and tests left out),
                      plus INFOPLIST_KEY_* build settings in *.xcodeproj/project.pbxproj for
                      projects that generate their Info.plist
  version fields      CFBundleShortVersionString and CFBundleVersion: present, well formed,
                      and the same across the app and its extensions; $(VARIABLE) values are
                      looked up in project.pbxproj
  purpose strings     every key ending in UsageDescription must be filled and not a placeholder;
                      and when Swift or Objective-C source uses an API from the usage table,
                      one of its keys must be present
  privacy manifest    PrivacyInfo.xcprivacy exists and parses; each required-reason category the
                      source appears to use is declared with at least one reason
  icons               an AppIcon set in an asset catalog lists images that exist; the
                      1024x1024 entry exists and its PNG has no alpha channel
  export compliance   ITSAppUsesNonExemptEncryption set (warning when absent)
  screenshots         with --screenshots: each PNG is readable, not blank, and its pixel size is
                      in the size table

The tables live in ../references/store-rules.json. They were written from memory and are
marked unverified; the script prints that. Apple's documentation is the source. Source
matching is by text, so it over-reports: a hit means "look", and the answer to declare is
what the code really does, never the answer that makes this check pass.

Not checked: review-guideline judgement, the store listing text, signing, and anything
App Store Connect decides on its own side.

Exit codes: 0 = no blocker found (warnings may be listed)
            1 = at least one blocker
            2 = blocked: no project, no Info.plist, or the rules file is missing
"""
import argparse
import json
import pathlib
import plistlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstat  # noqa: E402

RULES = pathlib.Path(__file__).resolve().parent.parent / "references" / "store-rules.json"
SKIP = {"build", "DerivedData", "Pods", ".git", "node_modules", ".build", "Carthage", ".mstack"}
PLACEHOLDER = re.compile(r"^\s*$|todo|tbd|fixme|placeholder|lorem|description here|\$\(", re.I)


def walk(root, pattern):
    for path in root.rglob(pattern):
        parts = set(path.relative_to(root).parts)
        if not parts & SKIP and not any(p.endswith(("Tests", "UITests")) for p in path.relative_to(root).parts[:-1]):
            yield path


def load_rules():
    data = json.loads(RULES.read_text(encoding="utf-8"))
    rules, notes = {}, []
    for name, entry in data.items():
        if isinstance(entry, dict) and "value" in entry:
            rules[name] = entry["value"]
            if not entry.get("verified"):
                notes.append(f"{name} (set {entry.get('checked', '?')})")
    return rules, notes


def build_settings(root):
    """Return {setting: set of values} from every project.pbxproj under root."""
    found = {}
    for pbx in walk(root, "project.pbxproj"):
        text = pbx.read_text(encoding="utf-8", errors="replace")
        for key, value in re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*\"?(.*?)\"?;\s*$", text, re.M):
            found.setdefault(key, set()).add(value.strip())
    return found


def resolve(value, settings):
    match = re.fullmatch(r"\$[({]([A-Z0-9_]+)[)}]", str(value).strip())
    if not match:
        return {str(value)}
    return settings.get(match.group(1), set())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=".", help="the app's folder (holds the .xcodeproj and the sources)")
    parser.add_argument("--screenshots", help="folder of store screenshots (PNG) to check against the size table")
    args = parser.parse_args()
    root = pathlib.Path(args.project)
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2
    try:
        rules, notes = load_rules()
    except (OSError, ValueError) as exc:
        print(f"blocked: the rules file {RULES} cannot be used ({exc})")
        return 2
    print("note: the rule tables are unverified, written from memory: " + ", ".join(notes) + ". Apple's documentation is the source.")
    blockers, warnings = [], []
    settings = build_settings(root)
    plists = {}
    for path in walk(root, "Info.plist"):
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
            if isinstance(data, dict):
                plists[path] = data
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            blockers.append(f"{path}: cannot be read as a property list ({exc})")
    generated = {k[len("INFOPLIST_KEY_"):]: sorted(v)[0] for k, v in settings.items() if k.startswith("INFOPLIST_KEY_")}
    if not plists and not generated:
        print(f"blocked: no Info.plist and no INFOPLIST_KEY_ build settings under {root}. Give the app's folder with --project.")
        return 2
    keys = dict(generated)
    for data in plists.values():
        keys.update({k: v for k, v in data.items() if k not in keys})
    print(f"read: {len(plists)} Info.plist files, {len(generated)} generated Info.plist keys from project.pbxproj")

    # version fields
    for field, setting in (("CFBundleShortVersionString", "MARKETING_VERSION"), ("CFBundleVersion", "CURRENT_PROJECT_VERSION")):
        values = set()
        for path, data in plists.items():
            if field not in data:
                blockers.append(f"{path.relative_to(root)}: no {field}")
            else:
                values |= resolve(data[field], settings)
        if not plists:
            values |= settings.get(setting, set())
        if len(values) > 1:
            blockers.append(f"{field} differs across targets: {', '.join(sorted(values))} (the app and its extensions should carry the same value)")
        for value in values:
            if not re.fullmatch(r"\d+(\.\d+){0,2}", value):
                blockers.append(f"{field} '{value}' is not one to three dot-separated numbers")
        if not values and plists:
            blockers.append(f"{field} could not be resolved to a value")
        print(f"version: {field} = {', '.join(sorted(values)) or 'not found'}")

    # purpose strings
    for key, value in sorted(keys.items()):
        if key.endswith("UsageDescription") and (not isinstance(value, str) or PLACEHOLDER.search(value) or len(value.strip()) < 12):
            blockers.append(f"{key} is empty or a placeholder ('{value}'); say plainly why the app needs it")
    sources = [p for ext in ("*.swift", "*.m", "*.mm") for p in walk(root, ext)]
    text = {p: p.read_text(encoding="utf-8", errors="replace") for p in sources}
    used = {}
    for symbol, wanted in rules["usage_keys"].items():
        hits = [p for p, t in text.items() if re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])", t)]
        if hits:
            used[symbol] = hits
            if not any(k in keys for k in wanted):
                blockers.append(f"source uses {symbol} ({hits[0].relative_to(root)}) but none of {', '.join(wanted)} is set")
    print(f"purpose strings: {sum(k.endswith('UsageDescription') for k in keys)} keys set; {len(sources)} source files scanned, {len(used)} sensitive APIs seen")

    # privacy manifest
    manifests = list(walk(root, "PrivacyInfo.xcprivacy"))
    declared = {}
    if not manifests:
        blockers.append("no PrivacyInfo.xcprivacy privacy manifest in the project")
    for path in manifests:
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            blockers.append(f"{path.relative_to(root)}: cannot be read ({exc})")
            continue
        for entry in data.get("NSPrivacyAccessedAPITypes", []) or []:
            category = entry.get("NSPrivacyAccessedAPIType", "")
            reasons = entry.get("NSPrivacyAccessedAPITypeReasons") or []
            declared[category] = declared.get(category, []) + list(reasons)
            if not reasons:
                blockers.append(f"{path.relative_to(root)}: {category} is declared with no reason")
    for category, needles in rules["required_reason_apis"].items():
        hits = [p for p, t in text.items() if any(n in t for n in needles)]
        if hits and category not in declared:
            blockers.append(f"source appears to use a {category.replace('NSPrivacyAccessedAPICategory', '')} API ({hits[0].relative_to(root)}) but the privacy manifest does not declare {category}")
    print(f"privacy manifest: {len(manifests)} found, {len(declared)} required-reason categories declared")

    # icons
    sets = [p for p in walk(root, "AppIcon.appiconset")]
    if not sets and "CFBundleIcons" not in keys:
        blockers.append("no AppIcon.appiconset in an asset catalog and no CFBundleIcons entry")
    try:
        limits, _ = pngstat.load_limits()
    except (OSError, ValueError):
        limits = None
    for folder in sets:
        try:
            images = json.loads((folder / "Contents.json").read_text(encoding="utf-8")).get("images", [])
        except (OSError, ValueError) as exc:
            blockers.append(f"{folder.relative_to(root)}: Contents.json cannot be read ({exc})")
            continue
        named = [i for i in images if i.get("filename")]
        if not named:
            blockers.append(f"{folder.relative_to(root)}: the icon set lists no image files")
        for image in named:
            file = folder / image["filename"]
            if not file.is_file():
                blockers.append(f"{folder.relative_to(root)}: listed icon {image['filename']} does not exist")
                continue
            if image.get("size") == "1024x1024" and image.get("idiom") in ("universal", "ios-marketing", None):
                info = pngstat.stats(file, limits) if limits else {}
                if not info.get("width"):
                    blockers.append(f"{file.relative_to(root)}: the 1024 icon is not a readable PNG ({info.get('error')})")
                elif (info["width"], info["height"]) != (1024, 1024):
                    blockers.append(f"{file.relative_to(root)}: the 1024 icon is {info['width']}x{info['height']}")
                elif info.get("alpha"):
                    blockers.append(f"{file.relative_to(root)}: the 1024 icon has an alpha channel")
        if not any(i.get("size") == "1024x1024" for i in named):
            blockers.append(f"{folder.relative_to(root)}: no 1024x1024 icon is listed")
    print(f"icons: {len(sets)} AppIcon sets")

    if "ITSAppUsesNonExemptEncryption" not in keys:
        warnings.append("ITSAppUsesNonExemptEncryption is not set; App Store Connect will ask the export-compliance question on every build")

    if args.screenshots:
        folder = pathlib.Path(args.screenshots)
        shots = sorted(folder.glob("*.png")) if folder.is_dir() else []
        if not shots:
            blockers.append(f"no PNG screenshots in {folder}")
        sizes = {tuple(s): name for name, pairs in rules["screenshot_sizes"].items() for s in pairs}
        for shot in shots:
            info = pngstat.stats(shot, limits) if limits else {}
            verdict, reason = pngstat.judge(info, limits) if limits else ("unknown", "no thresholds")
            dims = (info.get("width"), info.get("height"))
            device = sizes.get(dims) or sizes.get(dims[::-1])
            if verdict != "real":
                blockers.append(f"screenshot {shot.name}: {verdict} ({reason})")
            elif not device:
                blockers.append(f"screenshot {shot.name}: {dims[0]}x{dims[1]} is not a size in the table")
            else:
                print(f"screenshot: {shot.name} {dims[0]}x{dims[1]} -> {device} (size table unverified)")

    for line in blockers:
        print(f"blocker  {line}")
    for line in warnings:
        print(f"warn     {line}")
    print("not checked: review-guideline judgement, listing text, signing, and what App Store Connect checks on its side")
    if blockers:
        print(f"RESULT fail: {len(blockers)} blockers; first: {blockers[0]}")
        return 1
    print(f"RESULT pass: no blocker in the fields read ({len(warnings)} warnings); the rule tables are unverified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

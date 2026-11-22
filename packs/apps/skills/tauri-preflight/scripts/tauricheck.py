#!/usr/bin/env python3
"""Read a Tauri app's configuration and report what should be fixed before a release build.

  tauricheck.py [--project DIR]     DIR holds src-tauri/, or is src-tauri itself (default: .)

It reads tauri.conf.json (version 2 and version 1 shapes), src-tauri/Cargo.toml, package.json
and, for version 2, src-tauri/capabilities/*.json. It builds nothing and changes nothing.

Fields read
  version 2: identifier, version, app.security.csp, app.security.capabilities (inline),
             app.security.dangerousDisableAssetCspModification, app.withGlobalTauri,
             bundle.icon, bundle.createUpdaterArtifacts, plugins.updater.pubkey,
             plugins.updater.endpoints, plugins.updater.dangerousInsecureTransportProtocol,
             capabilities/*.json: windows, remote.urls, permissions (names and scopes)
  version 1: package.version, tauri.bundle.identifier, tauri.bundle.icon, tauri.security.csp,
             tauri.security.dangerousDisableAssetCspModification,
             tauri.security.dangerousRemoteDomainIpcAccess, tauri.allowlist (all modules),
             tauri.updater.active, tauri.updater.pubkey, tauri.updater.endpoints

FAIL (blocks)  identifier missing, malformed or still a template default; version fields that
               disagree between tauri.conf.json, Cargo.toml and package.json; no content security
               policy; a policy that lets scripts load from anywhere or allows inline or eval
               scripts; version 1 `allowlist.all` or `all` on a sensitive module; a scope that
               matches every path or every address; remote pages from any host given
               permissions; updater switched on with no public key, a plain-http endpoint or
               insecure transport allowed; no icon listed, or a listed icon missing or not the
               file type its name says.
WARN (listed)  things a person should decide: broad permission names, inline styles, shell
               execution, a global Tauri object, an identifier that ends in .app, and so on.

Limits, stated plainly: matching is by text and by name. Permission names come from a list
written from memory (references/tauri-rules.json, marked unverified), so a clean result does
not prove the permissions are narrow. Platform files such as tauri.macos.conf.json are not
merged; when one sets a field this script checks, the result is not verified. TOML and JSON5
configuration and TOML capability files are not read. Tauri's documentation is the source for
what each field means.

Exit codes: 0 = no failure (warnings may be listed)
            1 = at least one failure
            2 = blocked or not verified (no configuration found, unreadable file, unread override)
"""
import argparse
import json
import pathlib
import re
import sys

RULES_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "tauri-rules.json"
EVERYTHING = {"*", "**", "/*", "/**", "**/*", "$HOME/**", "~/**", "/"}
ANY_HOST = re.compile(r"^(\*{1,2}|(https?|wss?|\*)://\*{1,2}(:\*)?(/.*)?)$")
PLATFORM_FILES = ("macos", "linux", "windows", "android", "ios")
MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".icns": b"icns", ".ico": b"\x00\x00\x01\x00"}


class Findings:
    def __init__(self):
        self.rows = []

    def add(self, level, where, text):
        self.rows.append((level, where, text))

    def of(self, level):
        return [r for r in self.rows if r[0] == level]


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror or exc}"
    except ValueError as exc:
        return None, f"{path} is not valid JSON ({exc})"


def load_rules():
    data, error = read_json(RULES_FILE)
    if error:
        return None, error
    rules, notes = {}, []
    for name, entry in data.items():
        if isinstance(entry, dict) and "value" in entry:
            rules[name] = entry["value"]
            if not entry.get("verified"):
                notes.append(f"{name} (checked {entry.get('checked', '?')})")
    need = ("default_identifiers", "placeholder_identifier_parts", "broad_permission_patterns", "sensitive_allowlist_modules")
    lacking = [n for n in need if n not in rules]
    if lacking:
        return None, f"{RULES_FILE} lacks: {', '.join(lacking)}"
    return (rules, notes), None


def dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def cargo_version(path):
    """Return (version or None, note). Reads [package] version, following `version.workspace = true` one level up."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror or exc}"

    def section(body, name):
        found = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[|\Z)", body, re.M | re.S)
        return found.group(1) if found else ""

    package = section(text, "package")
    direct = re.search(r'^\s*version\s*=\s*"([^"]+)"', package, re.M)
    if direct:
        return direct.group(1), None
    if re.search(r"^\s*version\.workspace\s*=\s*true|^\s*version\s*=\s*\{\s*workspace\s*=\s*true", package, re.M):
        for parent in list(path.parent.parents)[:3]:
            root = parent / "Cargo.toml"
            if root.is_file():
                shared = re.search(r'^\s*version\s*=\s*"([^"]+)"', section(root.read_text(encoding="utf-8"), "workspace.package"), re.M)
                if shared:
                    return shared.group(1), None
        return None, f"{path} takes its version from a workspace, and no workspace version was found above it"
    return None, f"{path} has no version in its [package] section"


def parse_csp(value):
    """Return {directive: [sources]} or None when there is no policy."""
    if value is None or value == "" or value == {}:
        return None
    policy = {}
    if isinstance(value, str):
        for part in value.split(";"):
            words = part.split()
            if words:
                policy[words[0].lower()] = words[1:]
    elif isinstance(value, dict):
        for name, sources in value.items():
            policy[name.lower()] = sources.split() if isinstance(sources, str) else [str(s) for s in sources or []]
    else:
        return None
    return policy or None


def check_csp(f, value, where):
    policy = parse_csp(value)
    if policy is None:
        f.add("FAIL", where, "no content security policy is set: the web view may load and run content from anywhere")
        return
    if "default-src" not in policy:
        f.add("WARN", where, "the policy has no default-src, so anything it does not name is unrestricted")
    scripts = policy.get("script-src", policy.get("default-src", []))
    name = "script-src" if "script-src" in policy else "default-src"
    for source in scripts:
        bare = source.strip("'\"").lower()
        if source == "*" or ANY_HOST.match(source):
            f.add("FAIL", where, f"{name} allows scripts from any host ({source})")
        elif bare == "unsafe-eval":
            f.add("FAIL", where, f"{name} allows 'unsafe-eval': any string can be run as code")
        elif bare == "unsafe-inline":
            f.add("FAIL", where, f"{name} allows 'unsafe-inline' scripts: injected markup can run code")
        elif bare in ("http:", "https:", "data:", "blob:"):
            f.add("WARN", where, f"{name} allows the whole {bare} scheme")
    for directive, sources in policy.items():
        if directive == name:
            continue
        for source in sources:
            if source == "*" or ANY_HOST.match(source):
                f.add("WARN", where, f"{directive} allows any host ({source})")
            elif source.strip("'\"").lower() == "unsafe-inline" and directive.startswith("style-src"):
                f.add("WARN", where, f"{directive} allows inline styles")


def check_identifier(f, identifier, where, rules):
    if not identifier or not isinstance(identifier, str):
        f.add("FAIL", where, "no bundle identifier is set")
        return
    if not re.match(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$", identifier):
        f.add("FAIL", where, f"'{identifier}' is not a reverse-domain identifier (letters, digits, hyphens, at least one dot)")
        return
    low = identifier.lower()
    if low in [d.lower() for d in rules["default_identifiers"]]:
        f.add("FAIL", where, f"'{identifier}' is a template default; set the app's own identifier")
    else:
        part = next((p for p in rules["placeholder_identifier_parts"] if p.lower() in low), None)
        if part:
            f.add("FAIL", where, f"'{identifier}' still contains the placeholder '{part}'")
    if low.endswith(".app"):
        f.add("WARN", where, f"'{identifier}' ends in .app, which is also the extension of a Mac app bundle")


def check_versions(f, conf_version, conf_where, tauri_dir, project):
    seen = {}
    if isinstance(conf_version, str) and conf_version.endswith(".json"):
        target = (tauri_dir / conf_version).resolve()
        data, error = read_json(target)
        if error:
            f.add("UNREAD", conf_where, f"version points at {conf_version}: {error}")
        else:
            seen[f"tauri.conf.json (through {conf_version})"] = data.get("version")
    elif conf_version:
        seen["tauri.conf.json"] = conf_version
    else:
        f.add("WARN", conf_where, "no version in tauri.conf.json; Tauri falls back to Cargo.toml")
    cargo = tauri_dir / "Cargo.toml"
    if cargo.is_file():
        version, note = cargo_version(cargo)
        if version:
            seen["Cargo.toml"] = version
        else:
            f.add("UNREAD", "Cargo.toml", note)
    else:
        f.add("UNREAD", "Cargo.toml", f"no Cargo.toml in {tauri_dir}; the Rust crate's version was not compared")
    package = next((p for p in (project / "package.json", tauri_dir.parent / "package.json") if p.is_file()), None)
    if package:
        data, error = read_json(package)
        if error:
            f.add("UNREAD", "package.json", error)
        elif data.get("version"):
            seen["package.json"] = data["version"]
        else:
            f.add("WARN", "package.json", "package.json has no version field")
    values = {v for v in seen.values() if v}
    listing = ", ".join(f"{name} {value}" for name, value in seen.items())
    if len(values) > 1:
        f.add("FAIL", "version", f"version fields disagree: {listing}")
    return listing


def check_icons(f, icons, where, tauri_dir):
    if not icons or not isinstance(icons, list):
        f.add("FAIL", where, "no icon files are listed, so the bundle would have no icon of its own")
        return
    for entry in icons:
        path = tauri_dir / str(entry)
        if not path.is_file():
            f.add("FAIL", where, f"listed icon {entry} does not exist")
            continue
        head = path.read_bytes()[:8]
        magic = MAGIC.get(path.suffix.lower())
        if not head:
            f.add("FAIL", where, f"listed icon {entry} is an empty file")
        elif magic and not head.startswith(magic):
            f.add("FAIL", where, f"listed icon {entry} is not a real {path.suffix} file (wrong first bytes)")
    kinds = {pathlib.Path(str(e)).suffix.lower() for e in icons}
    if ".icns" not in kinds:
        f.add("WARN", where, "no .icns file is listed; a macOS bundle uses one")
    if ".ico" not in kinds:
        f.add("WARN", where, "no .ico file is listed; a Windows build uses one")


def check_updater(f, block, where, active=True):
    if not active:
        return False
    if not isinstance(block, dict):
        f.add("FAIL", where, "the updater is switched on but has no settings")
        return True
    key = block.get("pubkey")
    if not isinstance(key, str) or not key.strip():
        f.add("FAIL", where, "the updater is on with no public key (pubkey): updates could not be checked against a signature")
    elif len(key.strip()) < 40 or re.search(r"your|<|>|todo|xxx", key, re.I):
        f.add("FAIL", where, "the updater's pubkey looks like a placeholder, not a key")
    endpoints = block.get("endpoints")
    if not endpoints:
        f.add("WARN", where, "the updater has no endpoints in the configuration; if they are set in code, this script cannot see them")
    for url in endpoints or []:
        if str(url).lower().startswith("http://"):
            f.add("FAIL", where, f"updater endpoint uses plain http: {url}")
        elif not str(url).lower().startswith("https://"):
            f.add("WARN", where, f"updater endpoint is not an https address: {url}")
    if block.get("dangerousInsecureTransportProtocol"):
        f.add("FAIL", where, "dangerousInsecureTransportProtocol is true: updates may travel without TLS")
    return True


def scope_entries(value):
    """Yield every path or address string inside a scope value of any shape."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from scope_entries(item)
    elif isinstance(value, dict):
        for key in ("path", "url", "allow", "scope"):
            if key in value:
                yield from scope_entries(value[key])


def too_wide(entry):
    return entry in EVERYTHING or bool(ANY_HOST.match(entry))


def check_allowlist(f, allowlist, rules):
    where = "tauri.allowlist"
    if not isinstance(allowlist, dict):
        return 0
    if allowlist.get("all") is True:
        f.add("FAIL", where, "`all` is true: every API is open to the web view")
    count = 0
    for module, settings in allowlist.items():
        if not isinstance(settings, dict):
            continue
        count += 1
        if settings.get("all") is True:
            level = "FAIL" if module in rules["sensitive_allowlist_modules"] else "WARN"
            f.add(level, f"{where}.{module}", "`all` is true for this module")
        for entry in scope_entries(settings.get("scope")):
            if too_wide(entry):
                f.add("FAIL", f"{where}.{module}.scope", f"scope '{entry}' matches everything")
            elif "**" in entry:
                f.add("WARN", f"{where}.{module}.scope", f"scope '{entry}' is recursive")
        if module == "shell" and (settings.get("execute") is True or settings.get("sidecar") is True):
            f.add("WARN", f"{where}.shell", "the web view may start programs (execute or sidecar)")
    return count


def check_capability(f, cap, where, rules):
    if not isinstance(cap, dict):
        return 0
    urls = dig(cap, "remote", "urls") or []
    for url in urls:
        if too_wide(str(url)):
            f.add("FAIL", f"{where}: remote.urls", f"pages from any host ({url}) receive this capability's permissions")
    if urls and not any(too_wide(str(u)) for u in urls):
        f.add("WARN", f"{where}: remote.urls", f"remote pages receive permissions: {', '.join(map(str, urls))}")
    patterns = [re.compile(p) for p in rules["broad_permission_patterns"]]
    permissions = cap.get("permissions") or []
    for item in permissions:
        name = item if isinstance(item, str) else (item.get("identifier", "") if isinstance(item, dict) else "")
        if any(p.search(name) for p in patterns):
            f.add("WARN", f"{where}: permissions", f"'{name}' is a broad permission; confirm the app needs all of it")
        if isinstance(item, dict):
            for entry in scope_entries(item.get("allow")):
                if too_wide(entry):
                    f.add("FAIL", f"{where}: {name}", f"allow scope '{entry}' matches everything")
                elif "**" in entry:
                    f.add("WARN", f"{where}: {name}", f"allow scope '{entry}' is recursive")
    return len(permissions)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=".", help="the app's folder (holds src-tauri/), or src-tauri itself")
    args = parser.parse_args()
    project = pathlib.Path(args.project)
    tauri_dir = next((d for d in (project / "src-tauri", project) if (d / "tauri.conf.json").is_file()), None)
    if tauri_dir is None:
        other = [p.name for d in (project / "src-tauri", project) for p in d.glob("[Tt]auri*") if p.suffix in (".json5", ".toml")]
        if other:
            print(f"blocked: found {', '.join(other)} but only tauri.conf.json is read. Check that file by hand against Tauri's documentation.")
        else:
            print(f"blocked: no tauri.conf.json in {project / 'src-tauri'} or {project}. Give the app's folder with --project.")
        return 2
    loaded, error = load_rules()
    if error:
        print(f"blocked: {error}")
        return 2
    rules, notes = loaded
    conf_path = tauri_dir / "tauri.conf.json"
    conf, error = read_json(conf_path)
    if error or not isinstance(conf, dict):
        print(f"RESULT not verified: {error or conf_path.name + ' is not a JSON object'}")
        return 2
    if isinstance(conf.get("tauri"), dict) or isinstance(conf.get("package"), dict):
        shape = 1
    elif "identifier" in conf or isinstance(conf.get("app"), dict) or isinstance(conf.get("bundle"), dict):
        shape = 2
    else:
        print(f"RESULT not verified: {conf_path} has neither the version 1 keys (package, tauri) nor the version 2 keys (identifier, app, bundle)")
        return 2
    print(f"configuration: {conf_path} (version {shape} shape)")
    if notes:
        print("note: these lists are unverified, written from memory: " + ", ".join(notes) + ". Tauri's documentation is the source.")
    f = Findings()
    if shape == 2:
        check_identifier(f, conf.get("identifier"), "identifier", rules)
        versions = check_versions(f, conf.get("version"), "version", tauri_dir, project)
        check_csp(f, dig(conf, "app", "security", "csp"), "app.security.csp")
        if dig(conf, "app", "security", "dangerousDisableAssetCspModification"):
            f.add("WARN", "app.security.dangerousDisableAssetCspModification", "Tauri's own additions to the policy are switched off")
        if dig(conf, "app", "withGlobalTauri"):
            f.add("WARN", "app.withGlobalTauri", "the Tauri API is exposed on window; any script on the page can reach it")
        check_icons(f, dig(conf, "bundle", "icon"), "bundle.icon", tauri_dir)
        updater = dig(conf, "plugins", "updater")
        on = check_updater(f, updater, "plugins.updater", active=updater is not None)
        if dig(conf, "bundle", "createUpdaterArtifacts") and not on:
            f.add("FAIL", "bundle.createUpdaterArtifacts", "update files are built but plugins.updater has no public key to check them with")
        cargo_text = (tauri_dir / "Cargo.toml").read_text(encoding="utf-8") if (tauri_dir / "Cargo.toml").is_file() else ""
        if "tauri-plugin-updater" in cargo_text and not on:
            f.add("WARN", "plugins.updater", "Cargo.toml uses tauri-plugin-updater but the configuration has no updater section; settings made in code are not visible here")
        caps, perms = 0, 0
        for inline in dig(conf, "app", "security", "capabilities") or []:
            if isinstance(inline, dict):
                caps += 1
                perms += check_capability(f, inline, f"inline capability {inline.get('identifier', '?')}", rules)
        cap_dir = tauri_dir / "capabilities"
        for file in sorted(cap_dir.glob("*")) if cap_dir.is_dir() else []:
            if file.suffix == ".json":
                data, error = read_json(file)
                if error:
                    f.add("UNREAD", f"capabilities/{file.name}", error)
                    continue
                for cap in data if isinstance(data, list) else data.get("capabilities", [data]) if isinstance(data, dict) else []:
                    caps += 1
                    perms += check_capability(f, cap, f"capabilities/{file.name}", rules)
            elif file.suffix in (".toml", ".json5"):
                f.add("UNREAD", f"capabilities/{file.name}", "TOML and JSON5 capability files are not read by this script")
        permission_note = f"{caps} capabilities with {perms} permissions"
    else:
        check_identifier(f, dig(conf, "tauri", "bundle", "identifier"), "tauri.bundle.identifier", rules)
        versions = check_versions(f, dig(conf, "package", "version"), "package.version", tauri_dir, project)
        check_csp(f, dig(conf, "tauri", "security", "csp"), "tauri.security.csp")
        if dig(conf, "tauri", "security", "dangerousDisableAssetCspModification"):
            f.add("WARN", "tauri.security.dangerousDisableAssetCspModification", "Tauri's own additions to the policy are switched off")
        for entry in dig(conf, "tauri", "security", "dangerousRemoteDomainIpcAccess") or []:
            f.add("WARN", "tauri.security.dangerousRemoteDomainIpcAccess", f"a remote domain may call the app's commands: {dig(entry, 'domain')}")
        check_icons(f, dig(conf, "tauri", "bundle", "icon"), "tauri.bundle.icon", tauri_dir)
        updater = dig(conf, "tauri", "updater")
        check_updater(f, updater, "tauri.updater", active=bool(dig(updater, "active")))
        modules = check_allowlist(f, dig(conf, "tauri", "allowlist"), rules)
        permission_note = f"{modules} allowlist modules"
    extra_files = []
    for override in sorted(tauri_dir.glob("tauri.*.conf.json")):
        if override.name.split(".")[1] not in PLATFORM_FILES:
            extra_files.append(override.name)
            continue
        data, error = read_json(override)
        touched = sorted(set(data or {}) & {"identifier", "version", "app", "bundle", "plugins", "tauri", "package"}) if not error else ["(unreadable)"]
        if touched:
            f.add("UNREAD", override.name, f"this platform file sets {', '.join(touched)} and is merged over tauri.conf.json at build time; it was not merged here")

    print(f"checked: identifier, versions ({versions or 'none found'}), content security policy, {permission_note}, updater, icons")
    if extra_files:
        print(f"not read: {', '.join(extra_files)}. If the release build passes one of them with --config, its values replace what was checked here.")
    for level, title in (("FAIL", "fail"), ("UNREAD", "could not check"), ("WARN", "warn")):
        for _, where, text in f.of(level):
            print(f"{title:16} {where}: {text}")
    fails, unread, warns = f.of("FAIL"), f.of("UNREAD"), f.of("WARN")
    print(f"totals: {len(fails)} failures, {len(unread)} could not check, {len(warns)} warnings")
    if fails:
        print(f"RESULT fail: {len(fails)} failures; first: {fails[0][1]}: {fails[0][2]}")
        return 1
    if unread:
        print(f"RESULT not verified: {unread[0][1]}: {unread[0][2]}")
        return 2
    print(f"RESULT pass: no failure in the fields read ({len(warns)} warnings to decide on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

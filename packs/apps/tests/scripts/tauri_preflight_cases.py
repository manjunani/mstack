"""Test tauri-preflight's script on small Tauri-shaped projects this test writes.

Usage: python3 tauri_preflight_cases.py <new folder under .testrun/>

No Tauri project is built and neither cargo nor node is run. The configuration files are
written by hand in the two shapes the script knows. They were not produced by Tauri's own
project generator, so "the script reads what a real generated project contains" is not proven.
"""
import copy
import json
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "tauri-preflight" / "scripts" / "tauricheck.py"
PY = sys.executable
c = fx.Cases("tauri-preflight")
KEY = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEFCQ0RFRjAxMjM0NTY3ODkK"
CSP = "default-src 'self'; img-src 'self' asset: https://asset.localhost; style-src 'self'"

V2 = {"productName": "Notes", "version": "1.4.0", "identifier": "in.acme.notes",
      "app": {"security": {"csp": CSP}, "windows": [{"title": "Notes"}]},
      "bundle": {"active": True, "icon": ["icons/32x32.png", "icons/icon.icns", "icons/icon.ico"]},
      "plugins": {"updater": {"pubkey": KEY, "endpoints": ["https://updates.acme.in/{{target}}/{{current_version}}"]}}}
CAP = {"identifier": "main", "windows": ["main"], "permissions": ["core:default", "dialog:allow-open",
       {"identifier": "fs:allow-read-text-file", "allow": [{"path": "$APPDATA/notes/*"}]}]}
V1 = {"package": {"productName": "Notes", "version": "1.4.0"},
      "tauri": {"allowlist": {"all": False, "dialog": {"open": True}, "fs": {"readFile": True, "scope": ["$APPDATA/notes/*"]}},
                "bundle": {"identifier": "in.acme.notes", "icon": ["icons/32x32.png", "icons/icon.icns", "icons/icon.ico"]},
                "security": {"csp": CSP},
                "updater": {"active": True, "pubkey": KEY, "endpoints": ["https://updates.acme.in/{{target}}"]}}}
count = 0


def project(conf, cargo="1.4.0", package="1.4.0", caps=(CAP,), icons=True, extra=None):
    global count
    count += 1
    root = W / f"p{count:02d}"
    st = root / "src-tauri"
    (st / "icons").mkdir(parents=True)
    (st / "tauri.conf.json").write_text(json.dumps(conf, indent=2))
    if cargo:
        (st / "Cargo.toml").write_text(f'[package]\nname = "notes"\nversion = "{cargo}"\nedition = "2021"\n\n[dependencies]\ntauri = {{ version = "2" }}\n')
    if package:
        (root / "package.json").write_text(json.dumps({"name": "notes", "version": package}))
    if caps:
        (st / "capabilities").mkdir()
        for n, cap in enumerate(caps):
            (st / "capabilities" / f"cap{n}.json").write_text(json.dumps(cap))
    if icons:
        fx.write_png(st / "icons" / "32x32.png", fx.picture(32, 32))
        (st / "icons" / "icon.icns").write_bytes(b"icns" + b"\0" * 32)
        (st / "icons" / "icon.ico").write_bytes(b"\x00\x00\x01\x00" + b"\0" * 32)
    for name, text in (extra or {}).items():
        (st / name).parent.mkdir(parents=True, exist_ok=True)
        (st / name).write_text(text)
    return root


def changed(base, **paths):
    conf = copy.deepcopy(base)
    for dotted, value in paths.items():
        node, keys = conf, dotted.split("__")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        if value is None:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return conf


def check(want, label, root, *texts):
    c.run(want, label, [PY, SCRIPT, "--project", root])
    for text in texts:
        c.has(text)


# version 2
good = project(V2)
check(0, "v2: a sound configuration passes", good, "version 2 shape", "0 failures, 0 could not check, 0 warnings", "unverified, written from memory")
c.last_line("RESULT pass")
c.run(0, "v2: --project may be src-tauri itself", [PY, SCRIPT, "--project", good / "src-tauri"])
check(1, "v2: template identifier", project(changed(V2, identifier="com.tauri.dev")), "template default")
check(1, "v2: placeholder identifier", project(changed(V2, identifier="com.example.notes")), "placeholder 'example'")
check(1, "v2: identifier without a dot", project(changed(V2, identifier="notes")), "not a reverse-domain identifier")
check(1, "v2: no identifier", project(changed(V2, identifier=None)), "no bundle identifier")
check(0, "v2: identifier ending in .app only warns", project(changed(V2, identifier="in.acme.app")), "ends in .app")
check(1, "v2: Cargo.toml version differs", project(V2, cargo="1.3.9"), "version fields disagree", "Cargo.toml 1.3.9")
check(1, "v2: package.json version differs", project(V2, package="1.5.0"), "package.json 1.5.0")
check(0, "v2: no package.json, the other two agree", project(V2, package=None), "0 failures")
check(2, "v2: no Cargo.toml is not verified", project(V2, cargo=None), "the Rust crate's version was not compared")
check(0, "v2: version read through a path to package.json", project(changed(V2, version="../package.json")), "through ../package.json")
check(1, "v2: csp null", project(changed(V2, app__security__csp=None)), "no content security policy")
check(1, "v2: csp with wildcard default-src", project(changed(V2, app__security__csp="default-src *")), "allows scripts from any host")
check(1, "v2: csp with unsafe-eval", project(changed(V2, app__security__csp="default-src 'self'; script-src 'self' 'unsafe-eval'")), "unsafe-eval")
check(1, "v2: csp as an object with unsafe-inline scripts", project(changed(V2, app__security__csp={"default-src": "'self'", "script-src": ["'self'", "'unsafe-inline'"]})), "unsafe-inline")
check(0, "v2: subdomain wildcard and inline styles only warn", project(changed(V2, app__security__csp="default-src 'self'; connect-src https://*.acme.in; style-src 'self' 'unsafe-inline'")), "inline styles", "1 warnings")
check(0, "v2: connect-src to any host warns", project(changed(V2, app__security__csp="default-src 'self'; connect-src https://*")), "connect-src allows any host")
check(1, "v2: scope that matches the whole home folder", project(V2, caps=[{"identifier": "main", "windows": ["*"], "permissions": [{"identifier": "fs:allow-read-file", "allow": [{"path": "$HOME/**"}]}]}]), "matches everything")
check(1, "v2: http scope to any address", project(V2, caps=[{"identifier": "main", "permissions": [{"identifier": "http:default", "allow": [{"url": "https://*"}]}]}]), "allow scope 'https://*' matches everything")
check(1, "v2: remote pages from any host", project(V2, caps=[{"identifier": "r", "remote": {"urls": ["https://*"]}, "permissions": ["core:default"]}]), "pages from any host")
check(0, "v2: broad permission names warn", project(V2, caps=[{"identifier": "main", "permissions": ["shell:allow-execute", "fs:allow-home-read-recursive"]}]), "'shell:allow-execute' is a broad permission", "2 warnings")
check(1, "v2: inline capability with a root scope", project(changed(V2, app__security__capabilities=[{"identifier": "x", "permissions": [{"identifier": "fs:scope", "allow": ["/**"]}]}]), caps=()), "inline capability x")
check(2, "v2: TOML capability file is not read", project(V2, extra={"capabilities/extra.toml": 'identifier = "x"\n'}), "TOML and JSON5 capability files are not read")
check(1, "v2: updater with no pubkey", project(changed(V2, plugins__updater__pubkey="")), "no public key")
check(1, "v2: updater with a placeholder pubkey", project(changed(V2, plugins__updater__pubkey="YOUR_PUBLIC_KEY_HERE")), "placeholder")
check(1, "v2: updater with an http endpoint", project(changed(V2, plugins__updater__endpoints=["http://updates.acme.in/latest.json"])), "plain http")
check(1, "v2: updater with insecure transport allowed", project(changed(V2, plugins__updater__dangerousInsecureTransportProtocol=True)), "dangerousInsecureTransportProtocol")
check(1, "v2: update artifacts built but no updater key", project(changed(V2, plugins=None, bundle__createUpdaterArtifacts=True)), "update files are built")
check(0, "v2: no updater at all is fine", project(changed(V2, plugins=None)), "0 failures")
check(1, "v2: empty icon list", project(changed(V2, bundle__icon=[])), "no icon files are listed")
check(1, "v2: listed icons missing on disk", project(V2, icons=False), "listed icon icons/icon.icns does not exist")
check(1, "v2: an icon that is not the type its name says", project(V2, extra={"icons/icon.icns": "not an icon"}), "is not a real .icns file")
check(2, "v2: platform override file sets a checked field", project(V2, extra={"tauri.macos.conf.json": json.dumps({"identifier": "in.acme.notes.mac"})}), "was not merged here")
check(0, "v2: platform override file with unrelated keys is ignored", project(V2, extra={"tauri.macos.conf.json": json.dumps({"build": {}})}), "0 could not check")

check(0, "v2: a tauri.<name>.conf.json that is not a platform file is named, not judged (fault found on a real project)",
      project(V2, extra={"tauri.bundle.conf.json": json.dumps({"bundle": {"targets": ["dmg"]}})}), "not read: tauri.bundle.conf.json", "0 could not check")

# version 1
check(0, "v1: a sound configuration passes", project(V1, caps=()), "version 1 shape", "0 failures")
check(1, "v1: allowlist.all true", project(changed(V1, tauri__allowlist__all=True), caps=()), "every API is open")
check(1, "v1: fs.all true", project(changed(V1, tauri__allowlist__fs={"all": True}), caps=()), "tauri.allowlist.fs")
check(1, "v1: fs scope of everything", project(changed(V1, tauri__allowlist__fs={"readFile": True, "scope": ["**"]}), caps=()), "matches everything")
check(0, "v1: shell execute warns", project(changed(V1, tauri__allowlist__shell={"execute": True}), caps=()), "may start programs")
check(1, "v1: default identifier", project(changed(V1, tauri__bundle__identifier="com.tauri.dev"), caps=()), "template default")
check(1, "v1: updater active without pubkey", project(changed(V1, tauri__updater={"active": True, "endpoints": ["https://u.acme.in"]}), caps=()), "no public key")
check(0, "v1: updater present but inactive is not judged", project(changed(V1, tauri__updater={"active": False}), caps=()), "0 failures")
check(1, "v1: csp missing", project(changed(V1, tauri__security={}), caps=()), "no content security policy")
check(1, "v1: version mismatch", project(V1, caps=(), cargo="0.9.0"), "version fields disagree")

# several faults at once, and bad input
many = project(changed(V2, identifier="com.tauri.dev", app__security__csp=None, plugins__updater__pubkey=""), cargo="0.1.0")
check(1, "v2: four faults are all listed", many, "4 failures")
empty = W / "empty"
empty.mkdir()
check(2, "no tauri.conf.json: blocked", empty, "blocked: no tauri.conf.json")
(empty / "src-tauri").mkdir()
(empty / "src-tauri" / "Tauri.toml").write_text('identifier = "x.y"\n')
check(2, "only Tauri.toml: blocked, says it is not read", empty, "only tauri.conf.json is read")
bad = project(V2)
(bad / "src-tauri" / "tauri.conf.json").write_text("{ identifier: ")
check(2, "configuration that is not JSON: not verified", bad, "is not valid JSON")
odd = project({"name": "something else"})
check(2, "JSON with neither shape: not verified", odd, "neither the version 1 keys")
ws = project(V2, cargo=None)
(ws / "src-tauri" / "Cargo.toml").write_text('[package]\nname = "notes"\nversion.workspace = true\n')
(ws / "Cargo.toml").write_text('[workspace]\nmembers = ["src-tauri"]\n\n[workspace.package]\nversion = "1.4.0"\n')
check(0, "v2: Cargo version inherited from the workspace", ws, "Cargo.toml 1.4.0")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

#!/usr/bin/env python3
"""Start an app for a QA run, wait until it listens, and stop it afterwards.

  start   start a command in the background, wait until its port accepts connections
  wait    wait for a port that somebody else started
  status  list the servers this script started and whether they still listen
  stop    stop a server this script started (never any other process)

Examples:
  server.py start --name web --port 3000 -- npm run dev
  server.py start --name api --port 8000 --http-path /health -- python3 -m uvicorn app:app --port 8000
  server.py stop --name web

Exit codes: 0 = pass (listening, or stopped)
            1 = fail (the command exited, the port never opened, or the port is still held after stop)
            2 = blocked or not verified (port already in use, program not found, nothing to stop)
The log of each server is kept in .mstack/qa/servers/<name>.log. This script kills only process
groups it started itself and whose start time still matches its record.
"""
import argparse
import datetime
import http.client
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import time

STATE = pathlib.Path(".mstack") / "qa" / "servers"
TAIL = 15


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def started_at(pid):
    """The start time of a process as `ps` prints it. Used to notice a reused process id."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip()


def log_tail(path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-TAIL:]


def show_tail(path):
    lines = log_tail(path)
    if lines:
        print(f"--- last lines of {path}:")
        print("\n".join(lines))
    else:
        print(f"--- {path} is empty: the command printed nothing")


def kill_group(pgid, grace=5.0):
    """SIGTERM the group, wait, then SIGKILL what is left."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        end = time.time() + wait
        while time.time() < end:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            # reap the child if it is ours, so it does not linger as a zombie
            try:
                os.waitpid(-pgid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass
            time.sleep(0.1)
    return False


def http_answers(host, port, path):
    """True when a GET gets any HTTP answer below 500. Returns (ok, detail)."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", path)
        status = conn.getresponse().status
        conn.close()
    except (OSError, http.client.HTTPException) as exc:
        return False, f"no HTTP answer on {path}: {exc}"
    return status < 500, f"GET {path} answered {status}"


def state_file(root, name):
    return root / STATE / f"{name}.json"


def read_state(root, name):
    path = state_file(root, name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def ensure_ignore(root):
    ignore = root / ".mstack" / ".gitignore"
    line = "qa/servers/\n"
    old = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if line not in old:
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text(old + line, encoding="utf-8")


def cmd_start(root, args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("blocked: give the command to start after `--`")
        return 2
    if not hasattr(os, "killpg"):
        print("blocked: this script needs a POSIX system (macOS or Linux)")
        return 2
    old = read_state(root, args.name)
    if old and alive(old["pid"]) and started_at(old["pid"]) == old.get("started_at"):
        print(f"blocked: a server named '{args.name}' is already running (pid {old['pid']}, port {old['port']}). Stop it first: server.py stop --name {args.name}")
        return 2
    if port_open(args.host, args.port):
        print(f"blocked: {args.host}:{args.port} already accepts connections, so another process holds it. "
              "Stop that process yourself or pick another port; this script does not stop processes it did not start. "
              "If it is the app you want to test, use: server.py wait --port " + str(args.port))
        return 2
    cwd = (root / args.cwd).resolve() if args.cwd else root
    if not cwd.is_dir():
        print(f"blocked: working folder {cwd} does not exist")
        return 2
    if shutil.which(command[0], path=os.environ.get("PATH")) is None and not (cwd / command[0]).exists():
        print(f"blocked: program not found: {command[0]}. Install it or correct the command; nothing was started.")
        return 2

    folder = root / STATE
    folder.mkdir(parents=True, exist_ok=True)
    ensure_ignore(root)
    log_path = folder / f"{args.name}.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            print(f"blocked: could not start {command[0]}: {exc}")
            return 2
    print(f"started '{args.name}': {' '.join(command)}  (pid {proc.pid}, log {log_path})", flush=True)

    deadline = time.time() + args.timeout
    opened = False
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            print(f"the command exited with code {code} before {args.host}:{args.port} opened")
            show_tail(log_path)
            print(f"RESULT fail: '{args.name}' exited with code {code} before listening on port {args.port}")
            return 1
        if port_open(args.host, args.port):
            opened = True
            break
        time.sleep(0.2)
    if not opened:
        kill_group(proc.pid)
        show_tail(log_path)
        print(f"RESULT fail: port {args.port} did not open within {args.timeout} seconds; the process was stopped")
        return 1

    time.sleep(0.3)
    if proc.poll() is not None:
        show_tail(log_path)
        print(f"RESULT fail: '{args.name}' exited with code {proc.returncode} right after the port opened")
        return 1
    if args.http_path:
        ok, detail = http_answers(args.host, args.port, args.http_path)
        print(detail)
        if not ok:
            kill_group(proc.pid)
            show_tail(log_path)
            print(f"RESULT fail: the port is open but the app does not answer {args.http_path}; the process was stopped")
            return 1

    record = {"name": args.name, "pid": proc.pid, "pgid": proc.pid, "host": args.host, "port": args.port,
              "command": command, "cwd": str(cwd), "log": str(log_path), "started_at": started_at(proc.pid),
              "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    state_file(root, args.name).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"listening on {args.host}:{args.port} after {args.timeout - (deadline - time.time()):.1f}s")
    print(f"stop it with: server.py stop --name {args.name}")
    print("RESULT pass")
    return 0


def cmd_wait(root, args):
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if port_open(args.host, args.port):
            if args.http_path:
                ok, detail = http_answers(args.host, args.port, args.http_path)
                print(detail)
                if not ok:
                    print(f"RESULT fail: {args.host}:{args.port} is open but does not answer {args.http_path}")
                    return 1
            print(f"{args.host}:{args.port} accepts connections")
            print("RESULT pass")
            return 0
        time.sleep(0.2)
    print(f"RESULT fail: nothing listens on {args.host}:{args.port} after {args.timeout} seconds")
    return 1


def cmd_status(root, args):
    folder = root / STATE
    records = [read_state(root, p.stem) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    records = [r for r in records if r and (not args.name or r["name"] == args.name)]
    if not records:
        print("RESULT not verified: no server was started by this script in this project")
        return 2
    dead = 0
    for r in records:
        running = alive(r["pid"]) and started_at(r["pid"]) == r.get("started_at")
        listening = port_open(r["host"], r["port"])
        dead += not (running and listening)
        print(f"  {r['name']:12} pid {r['pid']:<7} {'running' if running else 'not running':12} "
              f"{r['host']}:{r['port']} {'listening' if listening else 'closed'}   {' '.join(r['command'])}")
    if dead:
        print(f"RESULT fail: {dead} recorded server(s) are not running or not listening")
        return 1
    print("RESULT pass")
    return 0


def cmd_stop(root, args):
    folder = root / STATE
    names = [p.stem for p in sorted(folder.glob("*.json"))] if args.all and folder.is_dir() else ([args.name] if args.name else [])
    if not names:
        print("RESULT not verified: nothing to stop: give --name, or no server was started by this script")
        return 2
    worst = 0
    for name in names:
        record = read_state(root, name)
        if record is None:
            print(f"'{name}': no record, so this script did not start it and will not stop it")
            worst = max(worst, 2)
            continue
        pid = record["pid"]
        if not alive(pid):
            print(f"'{name}': already stopped (pid {pid} is gone)")
        elif started_at(pid) != record.get("started_at"):
            print(f"'{name}': pid {pid} now belongs to a different process; left alone")
            worst = max(worst, 2)
            continue
        elif not kill_group(record["pgid"]):
            print(f"'{name}': could not stop process group {record['pgid']}")
            worst = max(worst, 1)
            continue
        else:
            print(f"'{name}': stopped (pid {pid})")
        end = time.time() + 3
        while time.time() < end and port_open(record["host"], record["port"]):
            time.sleep(0.2)
        if port_open(record["host"], record["port"]):
            print(f"'{name}': {record['host']}:{record['port']} still accepts connections: another process holds the port")
            worst = max(worst, 1)
        state_file(root, name).unlink(missing_ok=True)
    if worst == 1:
        print("RESULT fail: a server could not be stopped or its port is still held")
    elif worst == 2:
        print("RESULT not verified: at least one named server was not started by this script")
    else:
        print("RESULT pass")
    return worst


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("start", help="start a command and wait for its port")
    p.add_argument("--name", required=True, help="a short name for this server, used by stop and status")
    p.add_argument("--port", type=int, required=True, help="the port the command will listen on")
    p.add_argument("--host", default="127.0.0.1", help="host to probe (default 127.0.0.1)")
    p.add_argument("--timeout", type=float, default=60, help="seconds to wait for the port (default 60)")
    p.add_argument("--cwd", help="folder to start the command in, relative to --root")
    p.add_argument("--http-path", help="after the port opens, also require a GET on this path to answer below 500")
    p.add_argument("command", nargs=argparse.REMAINDER, help="the command, after `--`")

    p = sub.add_parser("wait", help="wait for a port somebody else opened")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--http-path", help="also require a GET on this path to answer below 500")

    p = sub.add_parser("status", help="list servers started by this script")
    p.add_argument("--name", help="only this server")

    p = sub.add_parser("stop", help="stop a server started by this script")
    p.add_argument("--name", help="the name given to start")
    p.add_argument("--all", action="store_true", help="stop every server this script started in this project")

    args = parser.parse_args()
    root = args.root.resolve()
    return {"start": cmd_start, "wait": cmd_wait, "status": cmd_status, "stop": cmd_stop}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

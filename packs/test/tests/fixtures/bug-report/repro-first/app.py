"""Tiny ticket tracker for the harbour office. Usage: python3 app.py"""
import json
import pathlib

STATE = pathlib.Path("state.json")


def load():
    if STATE.stat().st_size == 0:
        return {"tickets": []}
    return json.loads(STATE.read_text())


def main():
    state = load()
    open_tickets = [t for t in state["tickets"] if not t.get("closed")]
    print(f"{len(open_tickets)} open ticket(s)")


if __name__ == "__main__":
    main()

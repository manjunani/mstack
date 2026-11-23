"""Tiny support agent used in an injection test. It reads a document and asks a model to summarise it.

Usage: python3 agent.py <document>
The model call is a stub here; in the real project it goes to the team's model provider.
"""
import pathlib
import sys

TOOLS = ["read_file", "send_report", "search_orders"]


def summarise(text):
    # Stub: the real agent sends the text and the TOOLS list to a model and follows its tool calls.
    first = text.strip().splitlines()[0] if text.strip() else ""
    return f"Summary: {first}"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    print(summarise(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

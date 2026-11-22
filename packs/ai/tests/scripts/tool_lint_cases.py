"""Script test for tool-lint: definition files with one known defect each, and clean files in each shape.

Usage: tool_lint_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-tool-lint)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("tool-lint cases", args.folder)
LINT = casekit.SKILLS / "tool-lint" / "scripts" / "lint.py"


def tool(name, description, properties=None, required=None, key="input_schema"):
    schema = {"type": "object", "properties": properties if properties is not None else {}}
    if required is not None:
        schema["required"] = required
    return {"name": name, "description": description, key: schema}


def param(kind, description):
    return {"type": kind, "description": description}


ORDER = tool("get_order", "Returns one order with its lines and status. Use when the user asks about a single order and gives its number.",
             {"order_id": param("string", "The order number, for example A-1042.")}, ["order_id"])
REFUND = tool("create_refund", "Starts a refund for a paid order. Use only after the user has confirmed the amount; it moves money.",
              {"order_id": param("string", "The order number."), "amount": param("number", "Amount to refund, in the order's currency.")}, ["order_id", "amount"])
SEARCH = tool("search_products", "Finds products by words in their title. Use when the user describes an item without naming its id.",
              {"query": param("string", "Words to look for."), "limit": param("integer", "How many results to return.")}, ["query"])
t.json("good.json", [ORDER, REFUND, SEARCH])
t.run("three well written tools pass with no finding", LINT, ["good.json"], 0, contains=["0 FAIL, 0 WARN", "RESULT pass: no finding in 3 tools"])

t.json("openai.json", {"tools": [{"type": "function", "function": {"name": ORDER["name"], "description": ORDER["description"], "parameters": ORDER["input_schema"]}},
                                 {"name": SEARCH["name"], "description": SEARCH["description"], "inputSchema": SEARCH["input_schema"]}]})
t.run("function-wrapped and inputSchema shapes are read", LINT, ["openai.json"], 0, contains=["tools: 2 in 1 file", "no finding in 2 tools"])

t.json("names.json", [ORDER, dict(ORDER), tool("getOrder", "Looks up the shipping label of a parcel. Use when the user asks where a parcel is.", {}, []),
                      tool("run", "Executes the nightly stock report. Use when the user asks for yesterday's stock numbers.", {}, []),
                      tool("tool2", "Converts a price between two currencies. Use when the user gives an amount and two currency codes.", {}, []),
                      tool("list_orders", "Lists the orders of one customer, newest first. Use when the user asks what a customer bought.", {}, []),
                      tool("list_order", "Shows the packing list of a warehouse shelf. Use when staff ask what is stored on a shelf.", {}, []),
                      tool("oauth2_login", "Opens the sign-in page of the identity provider. Use when the session has expired.", {}, [])])
t.run("duplicate, colliding, near-copy and unclear names", LINT, ["names.json"], 1,
      contains=["2 FAIL, 3 WARN", "FAIL get_order + get_order: two tools are both named 'get_order'", "FAIL get_order + getOrder: the names differ only in case or separators",
                "WARN list_orders + list_order: the names are near copies", "WARN run: name 'run' does not say what the tool does", "WARN tool2: name 'tool2'"],
      absent=["WARN oauth2_login"])

t.json("descriptions.json", [tool("get_invoice", "", {}, []), tool("send_email", "Sends email.", {}, []),
                             tool("delete_draft", "Delete draft.", {}, []),
                             tool("count_rows", "Counts the rows of the table named in the argument and returns that number.", {}, [])])
t.run("missing, short, name-only and when-less descriptions", LINT, ["descriptions.json"], 1,
      contains=["FAIL get_invoice: no description", "WARN send_email: description has 2 words", "WARN delete_draft: description only repeats the name",
                "WARN count_rows: description does not say when to use the tool"], absent=["WARN count_rows: description has"])

schemas = [tool("set_price", "Changes the price of a product. Use when staff give a product id and a new price.",
                {"product_id": {"description": "The product."}, "price": param("number", "New price.")}, ["product_id", "amount"]),
           {"name": "ping_host", "description": "Checks that a host answers. Use when a user reports that a site is down."},
           {"name": "list_tags", "description": "Lists all tags. Use when the user wants to see which tags exist.", "input_schema": {"type": "array"}},
           tool("set_mode", "Switches the display mode. Use when the user asks for dark or light mode.", {"mode": {"type": "string", "enum": [], "description": "Mode."}}, ["mode"]),
           tool("add_note", "Adds a note to a customer record. Use when staff dictate a note for a customer.",
                {"customer": param("string", "Customer id."), "tags": {"type": "array", "description": "Tags."},
                 "author": {"type": "object", "description": "Who wrote it.", "properties": {"id": {}}}}),
           SEARCH]
t.json("schemas.json", schemas)
t.run("untyped parameters, bad required lists and missing schemas", LINT, ["schemas.json"], 1,
      contains=["FAIL set_price: parameters.product_id: no type", "FAIL set_price: parameters: required names 'amount', which is not a parameter",
                "FAIL ping_host: no input schema", 'FAIL list_tags: input schema type is "array"', "FAIL set_mode: parameters.mode: enum is empty",
                "WARN add_note: parameters: 3 parameters and no required list", "WARN add_note: parameters.tags: an array with no items schema",
                "FAIL add_note: parameters.author.id: no type", "1 of 6 tools with no finding"])

same = "Searches the knowledge base for articles that match the words given. Use when the user asks a how-to question."
t.json("overlap.json", [tool("search_kb", same, {}, []), tool("find_articles", same.replace("Searches", "Search"), {}, []),
                        tool("search_help", "Searches the knowledge base for help articles that match the given words. Use when the user asks a product question.", {}, []),
                        tool("search_tickets", "Searches the ticket system for tickets that match the words given. Use when the user asks about a past support case.", {}, []),
                        REFUND])
# Counted by hand after dropping filler words: search_kb and search_help share 9 of 11 distinct words (82%): a warning.
# search_tickets shares 5 of 15 with search_kb (33%): the same sentence frame with a different subject is not reported.
t.run("nearly identical descriptions fail, heavy overlap warns, a shared sentence frame does not", LINT, ["overlap.json"], 1,
      contains=["FAIL search_kb + find_articles: the descriptions are nearly the same text (100%", "WARN search_kb + search_help: the descriptions overlap heavily (82%"],
      absent=["create_refund +", "+ create_refund", "search_kb + search_tickets"])
t.run("a lower threshold reports the weaker pair too", LINT, ["overlap.json", "--overlap-warn", "0.3"], 1, contains=["WARN search_kb + search_tickets"])

t.json("warn-only.json", [ORDER, tool("count_rows", "Counts the rows of the table named in the argument and returns that number.", {"table": {"type": "string"}})])
t.run("warnings alone pass", LINT, ["warn-only.json"], 0, contains=["0 FAIL, 3 WARN", "judgement calls to read"])
t.run("warnings fail under --strict", LINT, ["warn-only.json", "--strict"], 1, contains=["3 WARN lines under --strict"])

t.json("second.json", [tool("get_order", "Fetches the delivery status of an order. Use when the user asks when an order arrives.", {}, [])])
t.run("the same name in two files fails", LINT, ["good.json", "second.json"], 1, contains=["two tools are both named 'get_order' (good.json#1 and second.json#1)"])

t.run("findings can be written to a new JSON file", LINT, ["names.json", "--json", "out.json"], 1, contains=["findings written to out.json"])
t.run("an existing JSON file is not overwritten", LINT, ["names.json", "--json", "out.json"], 2, contains=["RESULT blocked"])
t.write("broken.json", '[{"name": "x", ')
t.run("a file that is not JSON is blocked", LINT, ["broken.json"], 2, contains=["RESULT blocked", "not valid JSON"])
t.json("other.json", {"version": 2, "items": [1, 2, 3]})
t.run("a JSON file with no tools is blocked", LINT, ["other.json"], 2, contains=["holds no tool definitions"])
t.run("a missing file is blocked", LINT, ["nope.json"], 2, contains=["RESULT blocked: no file"])
sys.exit(t.done())

from flask import Flask, jsonify, request

from app.db import connect

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/orders")
def orders():
    customer = request.args.get("customer", "")
    rows = connect().execute(f"SELECT id, total FROM orders WHERE customer = '{customer}'").fetchall()
    return jsonify(rows)

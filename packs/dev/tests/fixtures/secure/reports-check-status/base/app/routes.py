from flask import Flask, jsonify

from app.db import connect

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(ok=True)

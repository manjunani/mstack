import requests
import yaml
from flask import Flask

app = Flask(__name__)


@app.get("/")
def index():
    return "harbour status service"

import sqlite3


def connect(path="shop.sqlite"):
    return sqlite3.connect(path)

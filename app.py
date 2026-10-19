import os
import secrets
from flask import Flask, request, abort

app = Flask(__name__)
TOKEN = os.environ["BUILD_TOKEN"]


def check_token():
    header = request.headers.get("Authorization", "")
    if not secrets.compare_digest(header.encode(), f"Bearer {TOKEN}".encode()):
        abort(401)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/build")
def build():
    check_token()
    return {"ok": True, "message": "token passt"}
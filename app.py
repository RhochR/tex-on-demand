import os
import re
import secrets
import tempfile
import zipfile
from flask import Flask, request, abort

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB Upload

TOKEN = os.environ["BUILD_TOKEN"]
MAX_UNZIPPED = 100 * 1024 * 1024  # 100 MB entpackt
MAIN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.tex")


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

    upload = request.files.get("file")
    if upload is None:
        abort(400, "no file uploaded")

    main = request.form.get("main", "main.tex")
    if not MAIN_PATTERN.fullmatch(main):
        abort(400, "invalid main file name")

    with tempfile.TemporaryDirectory() as work:
        zip_path = os.path.join(work, "src.zip")
        src = os.path.join(work, "src")
        upload.save(zip_path)

        try:
            with zipfile.ZipFile(zip_path) as z:
                if sum(info.file_size for info in z.infolist()) > MAX_UNZIPPED:
                    abort(413, "unpacked content too large")
                z.extractall(src)
        except zipfile.BadZipFile:
            abort(400, "not a zip file")

        if not os.path.isfile(os.path.join(src, main)):
            abort(400, f"{main} not found in zip")

        files = sorted(os.listdir(src))

    return {"ok": True, "main": main, "files": files}
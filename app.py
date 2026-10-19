import os
import re
import secrets
import subprocess
import tempfile
import zipfile
from flask import Flask, request, abort, Response

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB Upload

TOKEN = os.environ["BUILD_TOKEN"]
MAX_UNZIPPED = 100 * 1024 * 1024  # 100 MB entpackt
MAIN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.tex")
TIMEOUT_LIMIT = 10 # in Seconds


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

        result = subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode",
             "-halt-on-error", "-file-line-error", main],
            cwd=src,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=TIMEOUT_LIMIT
        )

        pdf_path = os.path.join(src, main[:-4] + ".pdf")
        if result.returncode != 0 or not os.path.isfile(pdf_path):
            return Response(result.stdout[-5000:], status=422,
                            mimetype="text/plain")

        with open(pdf_path, "rb") as f:
            pdf = f.read()

    return Response(pdf, mimetype="application/pdf")
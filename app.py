import os
import re
import secrets
import signal
import subprocess
import tempfile
import zipfile
from flask import Flask, request, abort, Response

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB Upload

TOKEN = os.environ["BUILD_TOKEN"]
MAX_UNZIPPED = 100 * 1024 * 1024  # 100 MB entpackt
MAIN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.tex")
TIMEOUT_LIMIT = 10  # in Sekunden, für den Betrieb eher 60 bis 120


def check_token():
    header = request.headers.get("Authorization", "")
    if not secrets.compare_digest(header.encode(), f"Bearer {TOKEN}".encode()):
        abort(401)


def run_latex(src, main):
    """Startet latexmk. Gibt (returncode, ausgabe) zurück, oder None bei Timeout."""
    env = {k: v for k, v in os.environ.items() if k != "BUILD_TOKEN"}
    env.update(shell_escape="f", openin_any="p", openout_any="p")

    proc = subprocess.Popen(
        ["latexmk", "-pdf", "-interaction=nonstopmode",
         "-halt-on-error", "-file-line-error", main],
        cwd=src,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=TIMEOUT_LIMIT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return None
    return proc.returncode, output


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

        result = run_latex(src, main)
        if result is None:
            return Response(f"build timeout after {TIMEOUT_LIMIT} s\n",
                            status=422, mimetype="text/plain")
        returncode, output = result

        pdf_path = os.path.join(src, main[:-4] + ".pdf")
        if returncode != 0 or not os.path.isfile(pdf_path):
            return Response(output[-5000:], status=422, mimetype="text/plain")

        with open(pdf_path, "rb") as f:
            pdf = f.read()

    return Response(pdf, mimetype="application/pdf")
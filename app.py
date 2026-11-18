import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import zipfile
from flask import Flask, request, abort, Response

app = Flask(__name__)


def fail(message):
    print(message, file=sys.stderr)
    # Exit code 4 is gunicorn's APP_LOAD_ERROR: the master shuts down
    # instead of respawning the worker in an endless loop.
    sys.exit(4)


def positive_int(name, default):
    """Liest eine positive Ganzzahl aus der Umgebung, sonst den Standardwert."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) <= 0:
        fail(f"{name} must be a positive whole number, got {raw!r}")
    return int(raw)


TOKEN = os.environ.get("BUILD_TOKEN", "")
if not TOKEN:
    fail(
        "BUILD_TOKEN is not set. Start the container with a token, e.g.:\n"
        '  docker run -p 8080:8000 -e BUILD_TOKEN="token" ghcr.io/rhochr/tex-on-demand:full'
    )

MAX_UPLOAD = positive_int("MAX_UPLOAD_MB", 20) * 1024 * 1024
MAX_UNZIPPED = positive_int("MAX_UNZIPPED_MB", 100) * 1024 * 1024
TIMEOUT_LIMIT = positive_int("BUILD_TIMEOUT", 30)  # in Sekunden
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
MAIN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.tex")


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
import os
import re
import secrets
import signal
import subprocess
import sys
import gzip
import io
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
OUTPUT_FORMATS = ("pdf", "zip")
MAX_ROOT_LENGTH = 1024


def check_token():
    header = request.headers.get("Authorization", "")
    if not secrets.compare_digest(header.encode(), f"Bearer {TOKEN}".encode()):
        abort(401)


def run_latex(src, main, synctex=False):
    """Startet latexmk. Gibt (returncode, ausgabe) zurück, oder None bei Timeout."""
    env = {k: v for k, v in os.environ.items() if k != "BUILD_TOKEN"}
    env.update(shell_escape="f", openin_any="p", openout_any="p")
    # Keine Zeilenumbrüche im Log, damit Pfade nicht zerschnitten werden
    # und Editoren (z.B. LaTeX Workshop) die Fehlermeldungen sauber parsen.
    env.update(max_print_line="10000")

    cmd = ["latexmk", "-pdf", "-interaction=nonstopmode",
           "-halt-on-error", "-file-line-error"]
    if synctex:
        cmd.append("-synctex=1")
    cmd.append(main)

    proc = subprocess.Popen(
        cmd,
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


def path_rewriter(src, root):
    """Ersetzt das temporäre Build-Verzeichnis durch `root` (oder entfernt es)."""
    if root:
        sep = "\\" if "\\" in root and "/" not in root else "/"
        replacement = (root.rstrip("/\\") + sep).encode()
    else:
        replacement = b""
    prefixes = []
    for base in {src, os.path.realpath(src)}:
        prefixes += [f"{base}/./".encode(), f"{base}/".encode()]

    def rewrite(data):
        for prefix in prefixes:
            data = data.replace(prefix, replacement)
        return data

    return rewrite


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def bundle(src, stem, rewrite):
    """Packt PDF, Log und SyncTeX (soweit vorhanden) in ein Zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        pdf = os.path.join(src, stem + ".pdf")
        if os.path.isfile(pdf):
            z.write(pdf, stem + ".pdf")

        log = os.path.join(src, stem + ".log")
        if os.path.isfile(log):
            z.writestr(stem + ".log", rewrite(read_file(log)))

        synctex = os.path.join(src, stem + ".synctex.gz")
        if os.path.isfile(synctex):
            with gzip.open(synctex, "rb") as f:
                data = rewrite(f.read())
            z.writestr(stem + ".synctex.gz", gzip.compress(data),
                       compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


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

    output_format = request.form.get("output", "pdf")
    if output_format not in OUTPUT_FORMATS:
        abort(400, "invalid output, use pdf or zip")

    root = request.form.get("root", "")
    if len(root) > MAX_ROOT_LENGTH or any(c in root for c in "\0\r\n"):
        abort(400, "invalid root")

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

        result = run_latex(src, main, synctex=output_format == "zip")
        if result is None:
            return Response(f"build timeout after {TIMEOUT_LIMIT} s\n",
                            status=422, mimetype="text/plain")
        returncode, output = result

        stem = main[:-4]
        pdf_path = os.path.join(src, stem + ".pdf")
        ok = returncode == 0 and os.path.isfile(pdf_path)
        log_path = os.path.join(src, stem + ".log")

        if output_format == "zip" and (ok or os.path.isfile(log_path)):
            if not ok and os.path.isfile(pdf_path):
                # Ein evtl. unvollständiges PDF nicht mitschicken.
                os.remove(pdf_path)
            data = bundle(src, stem, path_rewriter(src, root))
            return Response(data, status=200 if ok else 422,
                            mimetype="application/zip")

        if not ok:
            return Response(output[-5000:], status=422, mimetype="text/plain")

        pdf = read_file(pdf_path)

    return Response(pdf, mimetype="application/pdf")
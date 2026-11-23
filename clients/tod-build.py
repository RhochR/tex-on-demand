#!/usr/bin/env python3
"""Compile a LaTeX project on a tex-on-demand server.

Zips the folder of the main .tex file, sends it to the server and unpacks
the PDF, log and SyncTeX file next to it, so editors like VS Code with
LaTeX Workshop can show the PDF, errors and jump between PDF and source.

Only needs Python 3.8+ and its standard library.
"""

import argparse
import io
import os
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".config", "tex-on-demand", "token")

# Files LaTeX writes during a build. They are not sent to the server.
# PDFs are not in this list, because figures are often PDFs.
SKIP_SUFFIXES = (
    ".aux", ".log", ".synctex.gz", ".synctex", ".fls", ".fdb_latexmk",
    ".out", ".toc", ".lof", ".lot", ".bbl", ".blg", ".bcf", ".run.xml",
    ".nav", ".snm", ".vrb", ".xdv", ".dvi", ".tod-tmp",
)
SKIP_DIRS = {"node_modules", "__pycache__"}


def die(message, code=2):
    print(f"tex-on-demand: {message}", file=sys.stderr)
    sys.exit(code)


def read_token(args):
    if args.token:
        return args.token.strip()
    if os.environ.get("TOD_TOKEN", "").strip():
        return os.environ["TOD_TOKEN"].strip()
    path = args.token_file or os.environ.get("TOD_TOKEN_FILE") or TOKEN_FILE
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        token = ""
    if not token:
        die("no token found. Set TOD_TOKEN, pass --token, or put the token "
            f"into {TOKEN_FILE}")
    return token


def zip_project(project, main_pdf, outdir):
    """Packs the project folder into an in-memory zip, without build files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(project):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d not in SKIP_DIRS
                       and os.path.join(folder, d) != outdir]
            for name in files:
                path = os.path.join(folder, name)
                if (name.startswith(".") or name.endswith(SKIP_SUFFIXES)
                        or path == main_pdf):
                    continue
                z.write(path, os.path.relpath(path, project))
    return buf.getvalue()


def multipart(fields, file_field, file_name, file_data):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
            f"\r\n\r\n{value}\r\n".encode("utf-8"))
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_name}"\r\nContent-Type: application/zip\r\n\r\n'
        .encode("utf-8"))
    parts.append(file_data)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def write_atomic(path, data):
    """Writes via a temp file, so a PDF viewer never sees a half-written file."""
    tmp = path + ".tod-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def print_errors(log):
    """Prints the error lines of a LaTeX log (format `file:line: message`)."""
    lines = log.decode("utf-8", errors="replace").splitlines()
    errors = [line for line in lines
              if line.startswith("!") or ".tex:" in line.split(" ", 1)[0]]
    for line in errors[:20] or lines[-20:]:
        print(line, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Compile a LaTeX project on a tex-on-demand server.")
    parser.add_argument("main", help="path to the main .tex file")
    parser.add_argument("--url", default=os.environ.get("TOD_URL", ""),
                        help="server URL, e.g. http://localhost:8080 "
                             "(default: $TOD_URL)")
    parser.add_argument("--token", help="API token (default: $TOD_TOKEN, "
                                        f"then {TOKEN_FILE})")
    parser.add_argument("--token-file", help="file containing the API token")
    parser.add_argument("--outdir", help="where to put PDF, log and SyncTeX "
                                         "(default: folder of the main file)")
    parser.add_argument("--print-log", action="store_true",
                        help="print the full LaTeX log to stdout, so editors "
                             "that read the console output can show errors")
    parser.add_argument("--timeout", type=float, default=300,
                        help="seconds to wait for the server (default: 300)")
    args = parser.parse_args()

    if not args.url:
        die("no server URL. Set TOD_URL or pass --url")
    main_path = os.path.abspath(args.main)
    if not os.path.isfile(main_path) or not main_path.endswith(".tex"):
        die(f"{args.main} is not a .tex file")

    project = os.path.dirname(main_path)
    main_name = os.path.basename(main_path)
    stem = main_name[:-4]
    outdir = os.path.abspath(args.outdir) if args.outdir else project
    token = read_token(args)

    data = zip_project(project, os.path.join(project, stem + ".pdf"), outdir)
    body, content_type = multipart(
        {"main": main_name, "output": "zip", "root": project},
        "file", "project.zip", data)
    request = urllib.request.Request(
        args.url.rstrip("/") + "/build", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": content_type})

    print(f"tex-on-demand: compiling {main_name} on {args.url} "
          f"({len(data) // 1024} KB upload)")
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status, kind, payload = (response.status,
                                     response.headers.get_content_type(),
                                     response.read())
    except urllib.error.HTTPError as e:
        status, kind, payload = e.code, e.headers.get_content_type(), e.read()
    except (urllib.error.URLError, OSError) as e:
        die(f"could not reach {args.url}: {getattr(e, 'reason', e)}")

    if kind == "application/zip" and status in (200, 422):
        os.makedirs(outdir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names = set(z.namelist())
            if args.print_log and stem + ".log" in names:
                sys.stdout.write(z.read(stem + ".log")
                                 .decode("utf-8", errors="replace"))
                sys.stdout.flush()
            for name in (stem + ".log", stem + ".synctex.gz", stem + ".pdf"):
                if name in names:
                    write_atomic(os.path.join(outdir, name), z.read(name))
            if status == 200:
                print(f"tex-on-demand: wrote {stem}.pdf to {outdir}")
                return
            print("tex-on-demand: compilation failed", file=sys.stderr)
            if stem + ".log" in names:
                print_errors(z.read(stem + ".log"))
            sys.exit(1)

    text = payload.decode("utf-8", errors="replace").strip()
    if status == 401:
        die("the server rejected the token (401)")
    if status == 422:
        print("tex-on-demand: compilation failed", file=sys.stderr)
        print(text[-3000:], file=sys.stderr)
        sys.exit(1)
    die(f"server answered {status}: {text[:500]}")


if __name__ == "__main__":
    main()

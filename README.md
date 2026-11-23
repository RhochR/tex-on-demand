# tex-on-demand
An API that compiles LaTeX Documents, flexibly deployed with docker, built on TeXLive.

tex-on-demand comes in three variants:
- core  (contains a small texlive environment for compiling simple documents)
- standard  (contains additional packages for other languages, etc.)
- full  (contains EVERYTHING, almost...)

## Quick Start

Run one of the containers to test it out!

The API requires a secret token, passed via the `BUILD_TOKEN` environment variable.
Without it the container refuses to start. Inside the container the server listens on port `8000`.

```bash
docker run -p 8080:8000 -e BUILD_TOKEN="token" ghcr.io/rhochr/tex-on-demand:full
```

Replace `token` with your own secret. A random one can be generated with
`openssl rand -hex 32`. Replace `full` with `core` or `standard` for the
smaller variants.

Check that it is running:

```bash
curl http://localhost:8080/health
```

## Usage

Zip your project and send it to `/build`. Every request needs the header
`Authorization: Bearer <your token>`.

```bash
zip -r project.zip main.tex chapters/ images/
curl -X POST http://localhost:8080/build \
  -H "Authorization: Bearer token" \
  -F file=@project.zip \
  -F main=main.tex \
  -o main.pdf
```

- `file`: the zip archive (default limits: 20 MB upload, 100 MB unpacked)
- `main`: the main `.tex` file inside the zip (default: `main.tex`)
- `output`: `pdf` (default) or `zip`, see below
- `root`: optional, only used with `output=zip`, see below

On success the response is the PDF.

| Status | Meaning |
|---|---|
| `200` | Success, the body is the PDF |
| `400` | No file, not a zip, invalid `main` name or `main` file not found in the zip |
| `401` | Missing or wrong token |
| `413` | Upload or unpacked content larger than the configured limit |
| `422` | Compilation failed or took longer than `BUILD_TIMEOUT`. The body contains the end of the LaTeX log or the timeout message (with `output=zip`, see below). |

### Log and SyncTeX (`output=zip`)

Editors like VS Code with LaTeX Workshop need more than the PDF: the `.log`
file to show errors and warnings in the editor, and the `.synctex.gz` file to
jump between the PDF and the source. With `output=zip` the response is a zip
archive containing them:

```bash
curl -X POST http://localhost:8080/build \
  -H "Authorization: Bearer token" \
  -F file=@project.zip \
  -F main=main.tex \
  -F output=zip \
  -F root="$PWD" \
  -o result.zip
```

| Status | Body |
|---|---|
| `200` | Zip with `main.pdf`, `main.log` and `main.synctex.gz` |
| `422` | Zip with only `main.log` if compilation failed. On a timeout, or if no log was written at all, the body is plain text as in `pdf` mode. Check the `Content-Type` header (`application/zip` or `text/plain`). |

The names follow `main`, so `thesis.tex` gives `thesis.pdf`, `thesis.log` and
`thesis.synctex.gz`.

The server compiles in a temporary folder, so file paths in the log and
SyncTeX file are relative to the project root by default
(`chapters/intro.tex`). If you pass `root`, the absolute path of the project on
your machine, paths in the SyncTeX file and any absolute paths to the temporary
folder in the log are rewritten to start with it
(`/home/me/thesis/chapters/intro.tex`). Use this when your editor needs
absolute paths for SyncTeX. Windows paths like `C:\Users\me\thesis` work too.

## Configuration

All settings are passed as environment variables with `-e` on `docker run`.

| Variable | Default | Meaning |
|---|---|---|
| `BUILD_TOKEN` | (required) | Secret token clients send as `Authorization: Bearer <token>` |
| `MAX_UPLOAD_MB` | `20` | Maximum size of the uploaded zip in MB |
| `MAX_UNZIPPED_MB` | `100` | Maximum total size of the zip contents after unpacking in MB |
| `BUILD_TIMEOUT` | `30` | Maximum time in seconds a single compilation may take |

Example with all settings:

```bash
docker run -p 8080:8000 \
  -e BUILD_TOKEN="token" \
  -e MAX_UPLOAD_MB=50 \
  -e MAX_UNZIPPED_MB=500 \
  -e BUILD_TIMEOUT=120 \
  ghcr.io/rhochr/tex-on-demand:full
```

`MAX_UPLOAD_MB`, `MAX_UNZIPPED_MB` and `BUILD_TIMEOUT` must be positive whole
numbers. If a variable is not set or empty, the default is used. An invalid
value stops the container at startup with an error message.

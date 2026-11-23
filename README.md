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

The API has one endpoint for compiling: `POST /build`. You send your whole
LaTeX project as a zip file, the server compiles it with `latexmk` (pdfLaTeX)
and sends the result back.

Every request needs the header `Authorization: Bearer <your token>`, using the
same token you passed as `BUILD_TOKEN` when starting the container.

### Building a PDF

Zip your project, including every file the document needs (chapters, images,
bibliography, custom classes), and send it:

```bash
zip -r project.zip main.tex chapters/ images/
```

```bash
curl -X POST http://localhost:8080/build \
  -H "Authorization: Bearer token" \
  -F file=@project.zip \
  -F main=main.tex \
  -o main.pdf
```

If the build works, `main.pdf` is your document. If it fails, `main.pdf` is
not a PDF but a text file with the end of the LaTeX output, which tells you
what went wrong. Add `--fail-with-body` to the `curl` command if you want
`curl` to report the failure with a non-zero exit code.

### Request fields

| Field | Required | Meaning |
|---|---|---|
| `file` | yes | The zip archive with your project (default limits: 20 MB upload, 100 MB unpacked) |
| `main` | no | Path of the main `.tex` file inside the zip. It must be in the top folder of the zip and may only contain letters, digits, `_`, `-` and `.` (default: `main.tex`) |
| `output` | no | `pdf` (default) returns only the PDF. `zip` returns the PDF together with the log and SyncTeX file, see [Log and SyncTeX](#log-and-synctex) |
| `root` | no | Only used with `output=zip`. The absolute path of the project on your own computer, see [File paths and `root`](#file-paths-and-root) |

### Responses

| Status | Meaning |
|---|---|
| `200` | Success. The body is the PDF, or a zip with `output=zip` |
| `400` | No file, not a zip, invalid `main` name, `main` file not found in the zip, or an invalid `output` or `root` value |
| `401` | Missing or wrong token |
| `413` | Upload or unpacked content larger than the configured limit |
| `422` | Compilation failed or took longer than `BUILD_TIMEOUT`. The body contains the end of the LaTeX output or the timeout message as plain text. With `output=zip`, a failed compilation returns a zip with the log instead, see below |

### Log and SyncTeX

By default you only get the PDF back. That is enough for scripts, but editors
like VS Code with the LaTeX Workshop extension need two more files that LaTeX
writes during compilation:

- **`main.log`**, the full LaTeX log. Editors read it to show errors and
  warnings directly next to the line in your source that caused them.
- **`main.synctex.gz`**, the SyncTeX file. It maps every position in the PDF
  to a line in your source. Editors use it to jump from a line in the source
  to the matching spot in the PDF and back (for example with Ctrl+click in
  the PDF preview).

To get them, add `-F output=zip`. The response is then a zip archive instead
of a bare PDF:

```bash
curl -X POST http://localhost:8080/build \
  -H "Authorization: Bearer token" \
  -F file=@project.zip \
  -F main=main.tex \
  -F output=zip \
  -F root="$PWD" \
  -o result.zip
```

```bash
unzip -o result.zip
```

What the zip contains depends on the result:

| Status | Content type | Body |
|---|---|---|
| `200` | `application/zip` | `main.pdf`, `main.log` and `main.synctex.gz` |
| `422` | `application/zip` | Only `main.log`. Compilation failed, the log tells you why. No PDF is included, even if LaTeX wrote a partial one |
| `422` | `text/plain` | The build ran into `BUILD_TIMEOUT`, or LaTeX stopped before it could write a log. The body is the same plain text message as without `output=zip` |

So a `422` can be either a zip or plain text. A client should check the
`Content-Type` header before unpacking the response.

The file names follow `main`: with `-F main=thesis.tex` you get `thesis.pdf`,
`thesis.log` and `thesis.synctex.gz`.

Error messages in the log use the format `file:line: message`, for example
`./chapters/intro.tex:12: Undefined control sequence.`, and lines are not
wrapped. This is the format editors expect.

### File paths and `root`

The server compiles your project in a temporary folder that is deleted after
the build. The log and SyncTeX file would normally contain paths to that
folder, which mean nothing on your computer. The server therefore rewrites
them before sending the files back:

- **Without `root`**, paths to your files are relative to the top folder of
  the zip, for example `chapters/intro.tex`.
- **With `root`**, paths to your files start with the folder you passed. If
  your project lives in `/home/me/thesis` and you send
  `-F root=/home/me/thesis`, the SyncTeX file points to
  `/home/me/thesis/chapters/intro.tex`.

Pass `root` when you use the files in an editor. The SyncTeX file then points
to your files exactly where they are on your computer, so the editor does not
have to guess which folder relative paths belong to. In the `curl` example above,
`"$PWD"` sends the current folder, so run it from your project folder.

Windows paths work as well, for example `-F root="C:\Users\me\thesis"`.
`root` may be at most 1024 characters long and must not contain line breaks.

Files that come from TeX Live itself, such as `article.cls`, keep their paths
on the server. Editors simply ignore them.

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

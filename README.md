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

## Using it from VS Code

With the [LaTeX Workshop](https://marketplace.visualstudio.com/items?itemName=James-Yu.latex-workshop)
extension you can compile on a tex-on-demand server instead of a local TeX
installation. You keep the usual workflow: build on save, PDF preview next to
the source, errors in the Problems panel and SyncTeX jumps between PDF and
source. You do not need TeX Live on your computer, only Python 3.8 or newer.

### How it works

LaTeX Workshop normally runs `latexmk` on your computer. Instead, it can run
any program as a build tool. The script
[`clients/tod-build.py`](clients/tod-build.py) is such a tool:

1. It zips the folder that contains your main `.tex` file, with all
   subfolders. Build files (`.aux`, `.log`, `.synctex.gz` and similar),
   the old PDF of the main file, hidden files and folders like `.git`, and
   the output folder are left out. PDF figures are included.
2. It sends the zip to the server with `output=zip` and your project folder
   as `root`.
3. It unpacks the PDF, log and SyncTeX file into the output folder, where
   LaTeX Workshop picks them up. Files are replaced in one step, so the
   preview never shows a half-written PDF.

If the build fails, the old PDF stays in place, the new log is written, and
the script exits with an error, so LaTeX Workshop reports a failed build.

The main `.tex` file has to be in the top folder of your project, since the
script uploads the folder it is in.

### Setup

**1. Check that Python is installed.** Open a terminal and run:

```bash
python3 --version
```

On Windows, run `python --version` or `py --version` instead. You need 3.8 or
newer. If none of them works, install Python from
[python.org](https://www.python.org/downloads/). Remember which of the
commands worked, you need it in step 5.

**2. Get the server URL and token.** Start a server as described in
[Quick Start](#quick-start), or ask whoever runs one for you. For a server
on your own computer, the URL is `http://localhost:8080`.

If the server runs on another machine, it should be reachable over
`https://`. With plain `http://` the token and your documents travel
unencrypted through the network.

**3. Download the script.** Save
[`clients/tod-build.py`](clients/tod-build.py) somewhere it can stay, for
example in a folder `tools` in your home folder. Note the full path, for
example `/home/me/tools/tod-build.py` or `C:/Users/me/tools/tod-build.py`.
The script only uses the Python standard library, there is nothing else to
install.

**4. Save the token** in a file, so it does not end up in your VS Code
settings or in a repository.

On Linux and macOS:

```bash
mkdir -p ~/.config/tex-on-demand
```

```bash
echo "your-token" > ~/.config/tex-on-demand/token
```

On Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\tex-on-demand"
```

```powershell
Set-Content "$HOME\.config\tex-on-demand\token" "your-token"
```

Replace `your-token` with the real token.

**5. Test it in a terminal.** Go to the folder of a LaTeX project and run the
script on its main file:

```bash
python3 /home/me/tools/tod-build.py --url http://localhost:8080 main.tex
```

Use your Python command from step 1, your script path from step 3 and your
server URL. If it prints `wrote main.pdf`, everything works. If not, see
[Troubleshooting](#troubleshooting).

**6. Add the build tool to VS Code.** Open the Command Palette
(Ctrl+Shift+P, on macOS Cmd+Shift+P), run
*Preferences: Open User Settings (JSON)* and add these entries inside the
outer `{ }`:

```jsonc
"latex-workshop.latex.tools": [
  {
    "name": "tex-on-demand",
    "command": "python3",
    "args": [
      "/home/me/tools/tod-build.py",
      "--print-log",
      "--outdir",
      "%OUTDIR%",
      "%DOC_EXT%"
    ],
    "env": {
      "TOD_URL": "http://localhost:8080"
    }
  }
],
"latex-workshop.latex.recipes": [
  {
    "name": "tex-on-demand",
    "tools": ["tex-on-demand"]
  }
],
"latex-workshop.latex.recipe.default": "tex-on-demand",
"latex-workshop.latex.autoBuild.cleanAndRetry.enabled": false,
"latex-workshop.latex.autoBuild.run": "onSave"
```

Then change three things:

- `command`: your Python command from step 1
- the first entry in `args`: your script path from step 3. On Windows, use
  forward slashes (`C:/Users/me/tools/tod-build.py`), because single
  backslashes are not allowed in JSON
- `TOD_URL`: your server URL from step 2

Leave `%OUTDIR%` and `%DOC_EXT%` as they are. LaTeX Workshop replaces them
with the output folder and your main file.

What the other settings do:

- `recipe.default` makes tex-on-demand the recipe used for every build.
- `cleanAndRetry.enabled: false` stops LaTeX Workshop from building a second
  time after an error, which would just send the same failing project to the
  server again.
- `autoBuild.run: "onSave"` builds when you save a file. Use `"never"` if you
  only want to build by hand.

The same entries, with comments, are in
[`clients/vscode-settings.json`](clients/vscode-settings.json).

If your settings already contain `latex-workshop.latex.tools` or
`latex-workshop.latex.recipes`, add the tex-on-demand entries to the
existing lists instead of adding the keys a second time. Note that once you
set these lists, LaTeX Workshop's built-in recipes (like `latexmk`) are no
longer available, unless you add them to the lists too. To keep a local
recipe, add it after the tex-on-demand recipe and pick between them with
*LaTeX Workshop: Build with recipe*.

To use tex-on-demand only for one project, put the entries into the
project's `.vscode/settings.json` instead
(*Preferences: Open Workspace Settings (JSON)*).

**7. Build.** Open your main `.tex` file and save it, or run
*LaTeX Workshop: Build LaTeX project*. The PDF opens with
*LaTeX Workshop: View LaTeX PDF file*. The messages of the script are in the
*Output* panel under *LaTeX Compiler*.

### Script options

You can also run the script on its own, for example in a terminal or a CI job:

```bash
TOD_URL=http://localhost:8080 python3 tod-build.py main.tex
```

| Option | Meaning |
|---|---|
| `main` | Path to the main `.tex` file (required) |
| `--url` | Server URL. Default: the `TOD_URL` environment variable |
| `--token` | Token. Default: the `TOD_TOKEN` environment variable, then the token file |
| `--token-file` | File with the token. Default: `TOD_TOKEN_FILE`, then `~/.config/tex-on-demand/token` |
| `--outdir` | Where PDF, log and SyncTeX file are written. Default: the folder of the main file |
| `--print-log` | Also print the full LaTeX log to the console. The VS Code setup uses this, so LaTeX Workshop sees the errors in the compiler output as well as in the log file |
| `--timeout` | Seconds to wait for the server. Default: 300 |

Exit codes: `0` success, `1` compilation failed or timed out on the server,
`2` any other problem (no token, wrong token, server not reachable, invalid
arguments).

Avoid passing the token with `--token` in shared settings files, since it is
then stored in plain text there.

### Things to know

- **Every build uploads the whole project.** For big projects with many
  images this takes a moment, and the upload must stay below the server's
  `MAX_UPLOAD_MB`.
- **Only pdfLaTeX through `latexmk` is used.** Settings like
  `% !TEX program = xelatex` are ignored.
- **Only the project folder is uploaded.** Files outside the folder of the
  main file, for example `\input{../shared/macros}`, are not available on
  the server. Copy them into the project.
- **The main file name is restricted** to letters, digits, `_`, `-` and `.`,
  no spaces. Other `.tex` files in the project can be named freely.
- **The output folder must stay the same.** If you change
  `latex-workshop.latex.outDir`, delete the old output folder, otherwise it
  is uploaded with the project next time.

### Troubleshooting

The script tells you what went wrong. In VS Code you find its messages in the
*Output* panel under *LaTeX Compiler*.

| Message | Cause and fix |
|---|---|
| `no token found` | The token file does not exist or is empty. Repeat step 4 and check the path in the message |
| `the server rejected the token (401)` | The token is wrong. Compare the token file with the server's `BUILD_TOKEN`, and check for extra spaces |
| `no server URL` | `TOD_URL` is missing in the `env` of the tool, or `--url` is missing in the terminal |
| `could not reach ...` | Wrong URL, or the server is not running. Test it with `curl <url>/health` |
| `compilation failed` | Your document has an error. The lines below the message, and the Problems panel in VS Code, show the file and line |
| `build timeout after ... s` | The build took longer than the server's `BUILD_TIMEOUT` |
| `server answered 413` | The project is larger than the server allows (`MAX_UPLOAD_MB`, `MAX_UNZIPPED_MB`). Remove files the document does not need from the project folder |
| `server answered 400: invalid main file name` | The name of the main file contains characters other than letters, digits, `_`, `-` and `.`, for example spaces or umlauts. Rename it, for example to `main.tex` |
| `is not a .tex file` | The path to the main file is wrong |
| VS Code says the command `python3` was not found | Use the Python command that worked in step 1 for `command` |
| VS Code says the script was not found | The path in `args` is wrong. On Windows, check that you used forward slashes |

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

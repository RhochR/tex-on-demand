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
export BUILD_TOKEN="$(openssl rand -hex 32)"
docker run -p 8080:8000 -e BUILD_TOKEN ghcr.io/rhochr/tex-on-demand:full
```

Replace `full` with `core` or `standard` for the smaller variants.

Check that it is running:

```bash
curl http://localhost:8080/health
```

## Usage

Zip your project and send it to `/build`. Every request needs the header
`Authorization: Bearer <BUILD_TOKEN>`.

```bash
zip -r project.zip main.tex chapters/ images/
curl -X POST http://localhost:8080/build \
  -H "Authorization: Bearer $BUILD_TOKEN" \
  -F file=@project.zip \
  -F main=main.tex \
  -o main.pdf
```

- `file`: the zip archive (max. 20 MB, max. 100 MB unpacked)
- `main`: the main `.tex` file inside the zip (default: `main.tex`)

On success the response is the PDF. If compilation fails or exceeds the
30 second timeout, the server answers with `422` and the end of the LaTeX log.

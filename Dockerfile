ARG VARIANT=standard

FROM debian:stable-slim AS tex-core
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended lmodern cm-super \
      texlive-lang-german texlive-lang-english \
      texlive-plain-generic latexmk biber \
    && rm -rf /var/lib/apt/lists/*

FROM tex-core AS tex-standard
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-pictures texlive-science texlive-bibtex-extra \
      texlive-publishers texlive-humanities \
    && rm -rf /var/lib/apt/lists/*

FROM tex-standard AS tex-full
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-xetex texlive-luatex texlive-fonts-extra \
    && rm -rf /var/lib/apt/lists/*

FROM tex-${VARIANT} AS app
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-flask gunicorn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 builder
WORKDIR /srv
COPY app.py .
USER builder
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]
FROM debian:stable-slim

# 1. TeX Live (ändert sich fast nie)
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
      texlive-lang-german texlive-science texlive-pictures texlive-bibtex-extra \
      latexmk biber \
    && rm -rf /var/lib/apt/lists/*

# 2. Python, Flask und gunicorn
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-flask gunicorn \
    && rm -rf /var/lib/apt/lists/*

# 3. Benutzer ohne Root-Rechte
RUN useradd -m -u 1000 builder

# 4. Dein Code (ändert sich oft, deshalb ganz am Schluss)
WORKDIR /srv
COPY app.py .
USER builder
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]
# ─── Baza: Python 3.11 slim (Debian) - apt-get garantat disponibil ──
FROM python:3.11-slim-bookworm

# ─── Lambda Runtime Interface Client (inlocuieste baza AWS Lambda) ──
RUN pip install --no-cache-dir awslambdaric

# ─── Dependente Python ───────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Playwright instaleaza Chromium + toate dependentele automat ─────
#     (--with-deps se ocupa de apt-get intern, fara sa listam nimic)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium

# ─── Fontconfig: redirectam cache-ul in /tmp (writable in Lambda) ────
ENV HOME=/tmp
ENV FONTCONFIG_CACHE=/tmp/fontconfig
RUN mkdir -p /tmp/fontconfig

# ─── Setam directorul de lucru Lambda ───────────────────────────────
WORKDIR /var/task

# ─── Codul functiei Lambda ───────────────────────────────────────────
COPY bot_parcare_lambda.py .

# ─── Entry point Lambda ──────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
CMD ["bot_parcare_lambda.handler"]

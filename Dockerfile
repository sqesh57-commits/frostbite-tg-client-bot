FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    procps \
    psmisc \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash botuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R botuser:botuser /app

USER botuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501')" || exit 1

CMD ["streamlit", "run", "admin_panel.py", "--server.port", "8501", "--server.headless", "true"]

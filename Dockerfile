FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY templates /app/templates

WORKDIR /app/src

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python healthcheck.py

CMD ["python", "app.py"]

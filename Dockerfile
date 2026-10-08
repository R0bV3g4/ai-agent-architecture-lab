FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CREWAI_TELEMETRY_DISABLED=true \
    OTEL_SDK_DISABLED=true \
    CREWAI_STORAGE_DIR=/app/.crewai_storage

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 lab \
    && chown lab:lab /app

COPY --chown=lab:lab laboratorio_empresa.py opik_observability.py datadog_observability.py compliance.py .
USER lab
CMD ["python", "laboratorio_empresa.py"]

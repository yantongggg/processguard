FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY processguard ./processguard
COPY examples ./examples
COPY demo ./demo
COPY uipath ./uipath

RUN pip install --no-cache-dir -e ".[all]"

EXPOSE 8765

CMD uvicorn processguard.dashboard:app --host 0.0.0.0 --port ${PORT:-8765}
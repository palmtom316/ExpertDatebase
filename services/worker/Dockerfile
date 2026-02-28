FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    sqlalchemy \
    pydantic \
    pyyaml \
    requests \
    redis \
    minio \
    psycopg2-binary

COPY services/worker /app/services/worker
COPY shared /app/shared

ENV PYTHONPATH=/app/services/worker:/app

CMD ["python", "-m", "worker.main"]

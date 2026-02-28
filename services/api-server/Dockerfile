FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    sqlalchemy \
    pydantic \
    pyyaml \
    alembic \
    requests \
    redis \
    minio \
    psycopg2-binary \
    python-multipart

COPY services/api-server /app/services/api-server
COPY shared /app/shared

ENV PYTHONPATH=/app/services/api-server:/app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

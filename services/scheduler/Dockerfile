FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    requests

COPY services/scheduler /app/services/scheduler

ENV PYTHONPATH=/app/services/scheduler:/app

CMD ["python", "-m", "scheduler.main"]

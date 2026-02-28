"""Task queue adapters with in-memory and Redis backends."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import redis


class TaskQueue(Protocol):
    def enqueue_document_process(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def enqueue_document_process(self, payload: dict[str, Any]) -> None:
        self.jobs.append(payload)


class RedisTaskQueue:
    def __init__(self, redis_url: str, queue_name: str = "document:process") -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.queue_name = queue_name

    def enqueue_document_process(self, payload: dict[str, Any]) -> None:
        self.client.lpush(self.queue_name, json.dumps(payload, ensure_ascii=False))


def build_task_queue_from_env() -> TaskQueue:
    backend = os.getenv("TASK_QUEUE_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryTaskQueue()

    redis_url = os.getenv("REDIS_URL")
    queue_name = os.getenv("REDIS_QUEUE_NAME", "document:process")
    if redis_url:
        return RedisTaskQueue(redis_url=redis_url, queue_name=queue_name)
    return InMemoryTaskQueue()

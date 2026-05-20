import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "nhcx_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["common.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    # ── Route tasks to dedicated queues ───────────────────────────────────────────
    # nhcx-workers listen on 'nhcx' queue; abdm-workers listen on 'abdm' queue.
    # This keeps insurance and clinical workloads fully isolated.
    task_routes={
        "pdf2nhcx.tasks.process_nhcx_task": {"queue": "nhcx"},
        "pdf2abdm.tasks.process_abdm_task": {"queue": "abdm"},
    },
    task_default_queue="nhcx",  # safety net for any unrouted task
)

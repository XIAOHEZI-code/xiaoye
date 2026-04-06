from celery import Celery
from src.core.config import settings

app = Celery(
    "xiaoye_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.worker.tasks"]
)

# Optional configuration, see the application user guide.
app.conf.update(
    result_expires=3600,
    task_serializer='json',
    accept_content=['json'],  # Ignore other content
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Lock concurrency for heavy GPU marker tasks if run locally
    worker_concurrency=2,
    task_acks_late=True,
)

if __name__ == '__main__':
    app.start()

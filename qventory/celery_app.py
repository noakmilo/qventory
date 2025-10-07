"""
Celery Configuration for Qventory
Background task processing with Redis broker
"""
import os
from celery import Celery

# Get Redis URL from environment or use local default
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Create Celery instance
celery = Celery(
    'qventory',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['qventory.tasks']
)

# Celery Configuration
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
)

# Task routing
celery.conf.task_routes = {
    'qventory.tasks.import_ebay_inventory': {'queue': 'imports'},
    'qventory.tasks.process_ai_research': {'queue': 'ai'},
}

if __name__ == '__main__':
    celery.start()

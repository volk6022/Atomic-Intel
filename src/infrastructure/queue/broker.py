from taskiq_redis import ListQueueBroker
from src.core.config import settings

broker = ListQueueBroker(settings.REDIS_URL, queue_name="atomic_scraper_tasks")

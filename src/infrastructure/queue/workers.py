from src.infrastructure.queue.broker import broker


@broker.task
async def example_task():
    return "Hello from Taskiq!"

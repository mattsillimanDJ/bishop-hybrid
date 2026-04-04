from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routes.conversations import router as conversations_router
from app.routes.health import router as health_router
from app.routes.memory import router as memory_router
from app.routes.slack import router as slack_router
from app.services.conversation_log_service import init_conversation_log_table
from app.services.memory_service import init_db, seed_memory
from app.services.mode_service import init_mode_table
from app.services.provider_state_service import init_provider_table
from app.services.task_service import init_task_table


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_conversation_log_table()
    init_mode_table()
    init_provider_table()
    init_task_table()
    result = seed_memory()
    print(f"Memory startup: {result}")
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.include_router(health_router)
app.include_router(slack_router)
app.include_router(memory_router)
app.include_router(conversations_router)


@app.get("/")
def root():
    return {
        "message": "Bishop Hybrid is running",
        "environment": settings.APP_ENV,
    }

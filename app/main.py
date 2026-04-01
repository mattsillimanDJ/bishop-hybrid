from fastapi import FastAPI
from app.config import settings
from app.routes.health import router as health_router
from app.routes.slack import router as slack_router
from app.routes.memory import router as memory_router
from app.services.memory_service import init_db, seed_memory
from app.services.conversation_log_service import init_conversation_log_table
from app.routes.conversations import router as conversations_router

app = FastAPI(title=settings.APP_NAME)

app.include_router(health_router)
app.include_router(slack_router)
app.include_router(memory_router)
app.include_router(conversations_router)


@app.on_event("startup")
def startup_event():
    init_db()
    init_conversation_log_table()
    result = seed_memory()
    print(f"Memory startup: {result}")


@app.get("/")
def root():
    return {
        "message": "Bishop Hybrid is running",
        "environment": settings.APP_ENV,
    }

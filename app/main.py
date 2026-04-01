from fastapi import FastAPI
from app.config import settings
from app.routes.health import router as health_router
from app.routes.slack import router as slack_router
from app.routes.memory import router as memory_router
from app.services.memory_service import init_db, seed_memory

app = FastAPI(title=settings.APP_NAME)

app.include_router(health_router)
app.include_router(slack_router)
app.include_router(memory_router)


@app.on_event("startup")
def startup_event():
    init_db()
    result = seed_memory()
    print(f"Memory startup: {result}")


@app.get("/")
def root():
    return {
        "message": "Bishop Hybrid is running",
        "environment": settings.APP_ENV,
    }

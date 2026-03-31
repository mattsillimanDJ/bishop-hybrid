from fastapi import FastAPI
from app.config import settings
from app.routes.health import router as health_router
from app.routes.slack import router as slack_router

app = FastAPI(title=settings.APP_NAME)

app.include_router(health_router)
app.include_router(slack_router)


@app.get("/")
def root():
    return {
        "message": "Bishop Hybrid is running",
        "environment": settings.APP_ENV,
    }

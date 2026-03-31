import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Bishop Hybrid")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")


settings = Settings()

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Bishop Hybrid")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    BISHOP_AUTO_LISTEN_CHANNELS: str = os.getenv("BISHOP_AUTO_LISTEN_CHANNELS", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    CONSOLE_API_TOKEN: str = os.getenv("CONSOLE_API_TOKEN", "")

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").lower()

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    RESEARCH_PROVIDER: str = os.getenv("RESEARCH_PROVIDER", "none").lower()
    RESEARCH_API_KEY: str = os.getenv("RESEARCH_API_KEY", "")
    RESEARCH_API_URL: str = os.getenv("RESEARCH_API_URL", "")


settings = Settings()

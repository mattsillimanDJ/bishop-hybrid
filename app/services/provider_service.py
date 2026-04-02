from anthropic import Anthropic
from openai import OpenAI

from app.config import settings


def generate_text(provider: str, system_prompt: str, user_prompt: str) -> str:
    provider = (provider or settings.LLM_PROVIDER).lower()

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()

    if provider == "claude":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")

        try:
            client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            text_parts = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)

            return "".join(text_parts).strip()

        except Exception as e:
            print(f"[Bishop Claude Error] {type(e).__name__}: {str(e)}")
            raise

    raise ValueError(f"Unsupported provider: {provider}")


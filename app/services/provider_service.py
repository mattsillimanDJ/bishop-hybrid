from anthropic import Anthropic
from openai import OpenAI

from app.config import settings


VALID_PROVIDERS = {"openai", "claude"}


def get_provider_model(provider: str) -> str | None:
    provider = (provider or settings.LLM_PROVIDER).lower()

    if provider == "openai":
        return settings.OPENAI_MODEL or None

    if provider == "claude":
        return settings.ANTHROPIC_MODEL or None

    return None


def validate_provider_config(provider: str) -> tuple[bool, str]:
    provider = (provider or "").strip().lower()

    if provider not in VALID_PROVIDERS:
        return False, f"Unsupported provider: {provider}"

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            return False, "OPENAI_API_KEY is not set"
        if not settings.OPENAI_MODEL:
            return False, "OPENAI_MODEL is not set"
        return True, "OpenAI configuration looks valid"

    if provider == "claude":
        if not settings.ANTHROPIC_API_KEY:
            return False, "ANTHROPIC_API_KEY is not set"
        if not settings.ANTHROPIC_MODEL:
            return False, "ANTHROPIC_MODEL is not set"
        return True, "Claude configuration looks valid"

    return False, f"Unsupported provider: {provider}"


def generate_text(provider: str, system_prompt: str, user_prompt: str) -> str:
    provider = (provider or settings.LLM_PROVIDER).lower()

    is_valid, validation_message = validate_provider_config(provider)
    if not is_valid:
        raise ValueError(validation_message)

    if provider == "openai":
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty response")

        return content.strip()

    if provider == "claude":
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

            combined = "".join(text_parts).strip()
            if not combined:
                raise ValueError("Claude returned an empty response")

            return combined

        except Exception as e:
            print(f"[Bishop Claude Error] {type(e).__name__}: {str(e)}")
            raise ValueError(f"Claude request failed: {str(e)}") from e

    raise ValueError(f"Unsupported provider: {provider}")

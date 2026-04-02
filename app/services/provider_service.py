from openai import OpenAI
import anthropic

from app.config import settings

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


def generate_with_openai(system_prompt: str, user_prompt: str) -> str:
    if not settings.OPENAI_API_KEY:
        return "I’m missing an OpenAI API key."

    response = openai_client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.output_text.strip()


def generate_with_claude(system_prompt: str, user_prompt: str) -> str:
    if not settings.ANTHROPIC_API_KEY:
        return "I’m missing an Anthropic API key."

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=800,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )

    parts = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)

    return "\n".join(parts).strip()


def generate_text(system_prompt: str, user_prompt: str) -> str:
    provider = settings.LLM_PROVIDER

    if provider == "claude":
        return generate_with_claude(system_prompt, user_prompt)

    if provider == "openai":
        return generate_with_openai(system_prompt, user_prompt)

    return f"Unsupported LLM_PROVIDER: {provider}"

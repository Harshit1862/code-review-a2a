"""One place to create the chat model, so every agent uses the same provider settings."""

from common.config import settings


def get_llm():
    if settings.llm_provider == "fake":
        # Offline mode for testing the plumbing without an API key.
        from tests.fake_llm import FakeChatModel

        return FakeChatModel()

    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env or set LLM_PROVIDER=fake.")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0,  # same input -> same review
            max_retries=3,  # retries on rate limits (HTTP 429)
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. Use 'groq' or 'fake'.")

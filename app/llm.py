"""One-liner LLM helpers for every provider we have keys for.

from app.llm import ask, embed
ask("Summarise this: ...")                       # uses LLM_PROVIDER from .env
ask("...", provider="gemini")                    # anthropic | openai | featherless | gemini
ask("...", provider="featherless", model="meta-llama/Llama-3.3-70B-Instruct")
ask("...", system="Reply only with JSON.")
"""

from functools import cache

from app.config import settings

# OpenAI-compatible providers: name -> (base_url, key attr, default model attr)
OPENAI_COMPAT = {
    "openai": (None, "openai_api_key", "openai_model"),
    "featherless": ("https://api.featherless.ai/v1", "featherless_api_key", "featherless_model"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini_api_key",
        "gemini_model",
    ),
}
PROVIDERS = ["anthropic", *OPENAI_COMPAT]


@cache
def _openai_client(provider: str):
    from openai import OpenAI

    base_url, key_attr, _ = OPENAI_COMPAT[provider]
    return OpenAI(api_key=getattr(settings, key_attr), base_url=base_url)


@cache
def _anthropic_client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def ask(
    prompt: str,
    system: str = "",
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    provider = provider or settings.llm_provider
    if provider == "anthropic":
        import anthropic

        msg = _anthropic_client().messages.create(
            model=model or settings.anthropic_model,
            max_tokens=max_tokens,
            system=system or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    if provider not in OPENAI_COMPAT:
        raise ValueError(f"unknown provider {provider!r}, pick one of {PROVIDERS}")
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    r = _openai_client(provider).chat.completions.create(
        model=model or getattr(settings, OPENAI_COMPAT[provider][2]),
        messages=messages,
        max_tokens=max_tokens,
    )
    return r.choices[0].message.content or ""


def list_models(provider: str) -> list[str]:
    if provider == "anthropic":
        return [m.id for m in _anthropic_client().models.list()]
    return sorted(m.id for m in _openai_client(provider).models.list())


@cache
def _st(model: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model)


def embed(texts: list[str], model: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Local embeddings (GPU if available). Returns a normalised numpy array."""
    return _st(model).encode(texts, normalize_embeddings=True)

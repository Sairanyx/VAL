"""Verify every API key in .env works (one tiny real call each).
make keys            -> check all
make models-list P=gemini  -> list model ids for a provider"""

import sys

from app.config import settings
from app.llm import PROVIDERS, ask, list_models

KEYS = {
    "anthropic": settings.anthropic_api_key,
    "openai": settings.openai_api_key,
    "featherless": settings.featherless_api_key,
    "gemini": settings.gemini_api_key,
}


def hf_ok():
    import httpx

    r = httpx.get(
        "https://huggingface.co/api/whoami-v2",
        headers={"Authorization": f"Bearer {settings.hf_token}"},
    )
    r.raise_for_status()


def main() -> int:
    if len(sys.argv) > 1:
        print("\n".join(list_models(sys.argv[1])))
        return 0
    ok = True
    for p in PROVIDERS:
        if not KEYS[p]:
            print(f"  -  {p:12} not set")
            continue
        try:
            out = ask("Reply with just: ok", provider=p, max_tokens=20).strip()
            print(f"  OK {p:12} -> {out[:30]!r}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  XX {p:12} FAILED: {str(e)[:150]}")
    if settings.hf_token:
        try:
            hf_ok()
            print(f"  OK {'huggingface':12}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  XX {'huggingface':12} FAILED: {str(e)[:150]}")
    else:
        print(f"  -  {'huggingface':12} not set")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

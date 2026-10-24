"""Thin wrapper around the Google Gen AI SDK (pip install google-genai) -- free Google AI Studio key."""
from src import config


class GeminiNotConfigured(RuntimeError):
    pass


class GeminiBusy(RuntimeError):
    pass


# Tried in order; if a model name is retired/unavailable (404) the next one is used.
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
                   "gemini-2.0-flash", "gemini-2.0-flash-lite"]
_working_model = None
_client = None  # kept at module level so it is never garbage-collected/closed mid-request


def _new_client():
    global _client
    from google import genai
    from google.genai import types
    # Google AI Studio (free tier), NOT Vertex AI. 20s timeout per request so the app never hangs.
    _client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=20_000))
    return _client


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    global _working_model
    if not config.GEMINI_API_KEY:
        raise GeminiNotConfigured("Set GEMINI_API_KEY in env.txt (get one at https://aistudio.google.com/app/apikey)")
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature)

    candidates = [_working_model] if _working_model else []
    candidates += [m for m in [config.GEMINI_MODEL, *FALLBACK_MODELS] if m and m not in candidates]
    last_err, tried, busy_count = None, [], 0
    for model in candidates:
        if busy_count >= 3:          # don't keep the user waiting: give up after 3 busy models
            break
        try:
            resp = _call(model, prompt, cfg)
            _working_model = model
            return (resp.text or "").strip()
        except Exception as e:  # move on for "model not found" or "model busy"; other errors are real
            msg = str(e)
            last_err = e
            tried.append(f"{model}: {msg[:60]}")
            if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
                continue
            if _is_busy(msg):
                busy_count += 1
                if _working_model == model:
                    _working_model = None
                continue
            raise
    raise GeminiBusy("All Gemini models are busy/unavailable right now -- try again in a few minutes.\n"
                       + "\n".join(tried)) from last_err


def _is_busy(msg: str) -> bool:
    m = msg.lower()
    return any(t in m for t in ("503", "unavailable", "overloaded", "high demand", "timed out", "timeout",
                                "429", "resource_exhausted"))


def _call(model, prompt, cfg):
    """One request to one model; rebuilds the client once if the SDK reports it closed."""
    for attempt in range(2):
        client = _client or _new_client()
        try:
            return client.models.generate_content(model=model, contents=prompt, config=cfg)
        except Exception as e:
            if "client has been closed" in str(e).lower() and attempt == 0:
                _new_client()
                continue
            raise

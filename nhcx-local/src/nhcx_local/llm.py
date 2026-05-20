"""
llm.py -- Local LLM backend via Ollama.

Replaces the Vertex AI / Google Cloud calls from the hosted version
with a locally-running Ollama instance. All data stays on your machine.

Supported models (via Ollama):
    - gemma4:26b   (largest, highest quality)
    - gemma3        (default, good balance of speed and quality)
    - gemma2:27b    (larger, higher quality)
    - llama3.1:8b   (fast alternative)
    - qwen2.5:14b   (good for structured extraction)
    - Any model available in your Ollama instance

Prerequisites:
    1. Install Ollama: https://ollama.com/download
    2. Pull a model:   ollama pull gemma4:26b
    3. Ollama runs automatically on localhost:11434
"""

import os
import logging

logger = logging.getLogger(__name__)

# Default Ollama configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("NHCX_MODEL", "gemma4:26b")


def get_llm(model: str = None, temperature: float = 0.3, max_tokens: int = 8192):
    """
    Return a LangChain ChatOllama instance for local inference.

    Args:
        model:       Ollama model name (e.g. "gemma4:26b", "llama3.1:8b").
                     Defaults to NHCX_MODEL env var or "gemma4:26b".
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
        max_tokens:  Maximum output tokens.

    Returns:
        ChatOllama instance ready for .invoke() calls.
    """
    model = model or DEFAULT_MODEL

    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=model,
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
        num_predict=max_tokens,
    )

    logger.info(f"Using local Ollama model: {model} @ {OLLAMA_BASE_URL}")
    return llm


def check_ollama_health(model: str = None) -> tuple[bool, str]:
    """
    Check if Ollama is running and the requested model is available.

    Returns:
        (is_healthy, message) tuple.
    """
    model = model or DEFAULT_MODEL
    import urllib.request
    import json

    # Check if Ollama is running
    try:
        req = urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        data = json.loads(req.read().decode())
    except Exception as e:
        return False, (
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}.\n"
            f"Error: {e}\n\n"
            f"To fix this:\n"
            f"  1. Install Ollama: https://ollama.com/download\n"
            f"  2. Start Ollama:   ollama serve\n"
            f"  3. Pull a model:   ollama pull {model}"
        )

    # Check if the requested model is available
    available_models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
    # Also check full name with tag
    available_full = [m.get("name", "") for m in data.get("models", [])]

    if model in available_models or model in available_full:
        return True, f"Ollama is running. Model '{model}' is available."

    return False, (
        f"Ollama is running but model '{model}' is not installed.\n\n"
        f"Available models: {', '.join(available_full) or '(none)'}\n\n"
        f"To fix this:\n"
        f"  ollama pull {model}"
    )

"""
llm_inference_service.py — Vertex AI Model-as-a-Service (MaaS) LLM Client

Public API
----------
    from common.llm_inference_service import LlmInferenceService

    svc = LlmInferenceService()
    response_text = await svc.generate(
        prompt="Explain the difference between allergy and intolerance.",
        system_instruction="You are a medical expert assistant.",
        temperature=0.2,
        max_output_tokens=1024,
    )

Authentication
--------------
Uses the service account JSON specified by `llm_credentials_json` in Settings.
Falls back to Application Default Credentials (ADC).

API Schema
----------
Uses the native Vertex AI `generateContent` JSON schema.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


class LlmInferenceService:
    """
    Async wrapper around VertexAI MaaS endpoint (e.g., gemma-4-26b-a4b-it-maas).
    """

    def __init__(self) -> None:
        from common.config import get_settings
        self._settings = get_settings()
        self._client = None

    def _get_client(self):
        """Lazily build the auth client."""
        if self._client is not None:
            return self._client

        import google.auth
        from google.oauth2 import service_account

        creds_path = Path(self._settings.llm_credentials_json)
        if creds_path.is_file():
            credentials = service_account.Credentials.from_service_account_file(
                str(creds_path),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            logger.info("LlmInferenceService: loaded SA credentials from %s", creds_path)
        else:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            logger.info("LlmInferenceService: using Application Default Credentials")

        self._client = credentials
        return credentials

    def _refresh_token(self) -> str:
        """Get a fresh bearer token."""
        from google.auth.transport.requests import Request
        creds = self._get_client()
        if not creds.valid:
            creds.refresh(Request())
        return creds.token

    def _get_endpoint_url(self) -> str:
        """Construct the correct generateContent URL."""
        project = self._settings.llm_project_id
        location = self._settings.llm_location
        model = self._settings.llm_model

        # Global endpoint routing
        if location == "global":
            host = "aiplatform.googleapis.com"
        else:
            host = f"{location}-aiplatform.googleapis.com"

        # Usually models are under publishers/google/models/... but just in case
        # we append it directly.
        model_path = model if "publishers/" in model else f"publishers/google/models/{model}"

        url = f"https://{host}/v1/projects/{project}/locations/{location}/{model_path}:generateContent"
        return url

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
    ) -> str:
        """
        Generate text asynchronously via the Vertex AI API.
        """
        return await asyncio.to_thread(
            self._generate_sync,
            prompt,
            system_instruction,
            temperature,
            max_output_tokens,
        )

    def _generate_sync(
        self,
        prompt: str,
        system_instruction: str | None,
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        import urllib.request

        token = self._refresh_token()
        url = self._get_endpoint_url()

        # Build payload according to Vertex AI generateContent schema
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "role": "system",
                "parts": [{"text": system_instruction}],
            }

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    response_data = json.loads(resp.read().decode("utf-8"))
                    
                    # Parse candidates
                    candidates = response_data.get("candidates", [])
                    if not candidates:
                        return ""
                        
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if not parts:
                        return ""
                        
                    return parts[0].get("text", "")
                    
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8")
                logger.warning("Vertex API Error (%s): %s", exc.code, err_body)
                
                # Retry on 429 or 5xx
                if exc.code == 429 or exc.code >= 500:
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning("LlmInferenceService: Retrying in %.1fs…", delay)
                        time.sleep(delay)
                        continue
                raise RuntimeError(f"Vertex AI API Error: {exc.code} - {err_body}")
                
            except Exception as exc:
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("LlmInferenceService: attempt %d failed (%s). Retrying in %.1fs…", attempt + 1, exc, delay)
                    time.sleep(delay)
                else:
                    logger.error("LlmInferenceService: all retries exhausted: %s", exc)
                    raise

        return ""

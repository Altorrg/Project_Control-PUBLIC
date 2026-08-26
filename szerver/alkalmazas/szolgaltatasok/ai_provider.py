from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any
from urllib.parse import quote

import httpx

from ..adatmodellek.ai_asszisztens import AIAssistantRequest, AIAssistantSource
from ..beallitasok import Settings
from ..hibak import ServiceUnavailableError


logger = logging.getLogger("project_control.ai")

OPENAI_COMPATIBLE_PROVIDERS = {
    "openai",
    "openai-compatible",
    "openrouter",
    "groq",
    "bearer",
}
GENERIC_PROVIDERS = {"generic", "webhook", "x-api-key"}


@dataclass(slots=True)
class AIProviderResult:
    answer: str
    sources: list[AIAssistantSource] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _system_prompt(payload: AIAssistantRequest) -> str:
    context = ["A Project Control magyar nyelvű, belső projektirányítási alkalmazás asszisztense vagy."]
    if payload.module:
        context.append(f"Az aktuális modul technikai neve: {payload.module}.")
    if payload.project_id is not None:
        context.append(f"Az aktuális projekt azonosítója: {payload.project_id}.")
    context.extend(
        (
            "Magyarul, tömören és tényszerűen válaszolj.",
            "Ne állítsd, hogy látsz olyan projektadatot, amely nem szerepel az üzenetekben.",
            "Ne kérj és ne adj ki jelszót, API-kulcsot vagy más titkos adatot.",
        )
    )
    return " ".join(context)


def _conversation(payload: AIAssistantRequest) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _system_prompt(payload)}]
    messages.extend({"role": item.role, "content": item.content} for item in payload.history)
    messages.append({"role": "user", "content": payload.message})
    return messages


def _build_question(payload: AIAssistantRequest) -> str:
    lines = [_system_prompt(payload)]
    for item in payload.history:
        speaker = "Felhasználó" if item.role == "user" else "Asszisztens"
        lines.append(f"{speaker}: {item.content}")
    lines.append(f"Felhasználó: {payload.message}")
    return "\n\n".join(lines)


def _openai_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.casefold().endswith("/chat/completions") else f"{url}/chat/completions"


def _gemini_url(base_url: str, model: str) -> str:
    url = base_url.rstrip("/")
    if ":generatecontent" in url.casefold():
        return url
    if "/models/" in url.casefold():
        return f"{url}:generateContent"
    return f"{url}/models/{quote(model, safe='-_.')}:generateContent"


def _request_parts(
    settings: Settings,
    payload: AIAssistantRequest,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    provider = settings.ai_provider.strip().casefold()
    common_headers = {"Accept": "application/json", "Content-Type": "application/json"}

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return (
            _openai_url(settings.ai_api_base_url),
            {**common_headers, "Authorization": f"Bearer {settings.ai_api_key}"},
            {
                "model": settings.ai_model,
                "messages": _conversation(payload),
                "temperature": 0.2,
            },
        )

    if provider in {"gemini", "google"}:
        contents = []
        for item in payload.history:
            contents.append(
                {
                    "role": "user" if item.role == "user" else "model",
                    "parts": [{"text": item.content}],
                }
            )
        contents.append({"role": "user", "parts": [{"text": payload.message}]})
        return (
            _gemini_url(settings.ai_api_base_url, settings.ai_model),
            {**common_headers, "x-goog-api-key": settings.ai_api_key},
            {
                "system_instruction": {"parts": [{"text": _system_prompt(payload)}]},
                "contents": contents,
                "generationConfig": {"temperature": 0.2},
            },
        )

    if provider == "anthropic":
        return (
            settings.ai_api_base_url,
            {
                **common_headers,
                "x-api-key": settings.ai_api_key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": settings.ai_model,
                "system": _system_prompt(payload),
                "messages": [
                    *({"role": item.role, "content": item.content} for item in payload.history),
                    {"role": "user", "content": payload.message},
                ],
                "max_tokens": 1200,
                "temperature": 0.2,
            },
        )

    if provider in GENERIC_PROVIDERS:
        return (
            settings.ai_api_base_url,
            {**common_headers, "x-api-key": settings.ai_api_key},
            {"kerdes": _build_question(payload), "model": settings.ai_model},
        )

    raise ServiceUnavailableError(
        "Az AI-asszisztens szolgáltatója nincs támogatott módon beállítva."
    )


def _text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"].strip())
        return "\n".join(text for text in texts if text)
    return ""


def _extract_answer(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""

    for key in ("valasz", "answer", "response", "text", "output_text"):
        answer = _text_from_content(data.get(key))
        if answer:
            return answer

    message = data.get("message")
    if isinstance(message, dict):
        answer = _text_from_content(message.get("content") or message.get("text"))
        if answer:
            return answer
    elif isinstance(message, str) and message.strip():
        return message.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice_message = choices[0].get("message")
        if isinstance(choice_message, dict):
            answer = _text_from_content(choice_message.get("content"))
            if answer:
                return answer
        answer = _text_from_content(choices[0].get("text"))
        if answer:
            return answer

    content = data.get("content")
    answer = _text_from_content(content)
    if answer:
        return answer

    candidates = data.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        candidate_content = candidates[0].get("content")
        if isinstance(candidate_content, dict):
            return _text_from_content(candidate_content.get("parts"))
    return ""


def _provider_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return "Az AI-asszisztens szolgáltatói hitelesítése hibás vagy lejárt."
    if status_code == 429:
        return "Az AI-asszisztens szolgáltatója túlterhelt. Próbáld meg később."
    return "Az AI-asszisztens szolgáltatás jelenleg nem érhető el."


async def generate_ai_assistant_response(
    settings: Settings,
    payload: AIAssistantRequest,
    *,
    client: httpx.AsyncClient | None = None,
) -> AIProviderResult:
    url, headers, body = _request_parts(settings, payload)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        timeout=settings.ai_request_timeout_seconds,
        follow_redirects=False,
    )
    try:
        response = await http_client.post(url, headers=headers, json=body)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        logger.warning("AI szolgáltató hálózati hiba: %s", exc.__class__.__name__)
        raise ServiceUnavailableError(
            "Az AI-asszisztens szolgáltatás jelenleg nem érhető el."
        ) from exc
    finally:
        if owns_client:
            await http_client.aclose()

    if response.status_code >= 400:
        logger.warning(
            "AI szolgáltató hibás válasz provider=%s status=%s",
            settings.ai_provider,
            response.status_code,
        )
        raise ServiceUnavailableError(_provider_error_message(response.status_code))

    try:
        data = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            return AIProviderResult(answer=text)
        logger.warning("AI szolgáltató nem JSON választ adott")
        raise ServiceUnavailableError("Az AI-asszisztens válasza nem értelmezhető.")

    answer = _extract_answer(data)
    if not answer:
        logger.warning("AI szolgáltató válaszában nincs szöveg provider=%s", settings.ai_provider)
        raise ServiceUnavailableError("Az AI-asszisztens válasza nem értelmezhető.")
    return AIProviderResult(answer=answer)

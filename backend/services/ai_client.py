"""
Minimal xAI / SpaceXAI HTTP client (OpenAI-compatible chat completions).

Server-side only. Never log API keys or full prompts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


ChatTransport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            snippet = (resp.text or "").strip().replace("\n", " ")[:180]
            raise RuntimeError(
                f"Grok API error HTTP {resp.status_code}"
                + (f": {snippet}" if snippet else ". Check key and model access.")
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Grok API returned unexpected payload")
        return data


def chat_json(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 60.0,
    transport: ChatTransport | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> ChatResult:
    """
    Chat completion expecting a JSON object in the assistant message.
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY is not configured")
    base = (base_url or "https://api.x.ai/v1").rstrip("/")
    url = f"{base}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
    }
    if tools:
        body["tools"] = tools
    else:
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    runner = transport or _default_transport
    try:
        data = runner(url, headers, body, timeout)
    except httpx.TimeoutException as exc:
        logger.warning("Grok API timeout model=%s", model)
        raise RuntimeError("Grok API timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("Grok API network error: %s", type(exc).__name__)
        raise RuntimeError("Grok API network error") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Grok API returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        # Some multimodal shapes — join text parts
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
            elif isinstance(p, str):
                parts.append(p)
        content = "".join(parts)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Grok API returned empty content")

    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))

    return ChatResult(
        content=content.strip(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=str(data.get("model") or model),
    )


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse model JSON; tolerate optional markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Model JSON must be an object")
    return data

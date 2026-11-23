"""Multi-tier LLM orchestrator with 413 semantic chunking and 429 jittered backoff."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised on HTTP 429 Too Many Requests."""

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PayloadTooLargeError(Exception):
    """Raised on HTTP 413 Payload Too Large."""


def distill_html(html: str) -> str:
    """Strip scripts, styles, nav, and boilerplate while preserving semantic text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "aside", "iframe"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


def chunk_text_semantic(text: str, max_chars: int = 12000, overlap_chars: int = 400) -> List[str]:
    """Split distilled text along paragraph boundaries to avoid 413 errors."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n")
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for para in paragraphs:
        if len(para) > max_chars:
            # Hard-split oversized single lines cleanly
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            for i in range(0, len(para), max_chars - overlap_chars):
                chunks.append(para[i : i + max_chars])
            continue

        if current_len + len(para) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            # Retain trailing overlap context
            tail = "\n".join(current)[-overlap_chars:]
            current = [tail, para] if tail else [para]
            current_len = sum(len(x) + 1 for x in current)
        else:
            current.append(para)
            current_len += len(para) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


@dataclass
class LLMTier:
    name: str
    model: str
    handler: Callable[[str, str], Awaitable[str]]


class MultiTierLLMOrchestrator:
    """Executes extraction across Gemini Flash -> Groq Llama 3 -> DeepSeek with 429/413 resilience."""

    def __init__(
        self,
        tiers: Optional[List[LLMTier]] = None,
        max_retries_per_tier: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        max_chars_per_call: int = 12000,
    ) -> None:
        self.tiers = tiers or self._default_tiers()
        self.max_retries_per_tier = max_retries_per_tier
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_chars_per_call = max_chars_per_call

    def _default_tiers(self) -> List[LLMTier]:
        return [
            LLMTier("gemini", "gemini-2.5-flash", self._call_gemini),
            LLMTier("groq", "llama-3.3-70b-versatile", self._call_groq),
            LLMTier("deepseek", "deepseek-chat", self._call_deepseek),
        ]

    async def extract_structured(self, raw_html_or_text: str, schema_prompt: str) -> Dict[str, Any]:
        clean_text = distill_html(raw_html_or_text) if "<" in raw_html_or_text else raw_html_or_text
        chunks = chunk_text_semantic(clean_text, max_chars=self.max_chars_per_call)

        merged: Dict[str, Any] = {}
        for idx, chunk in enumerate(chunks):
            prompt = f"{schema_prompt}\n\n[Chunk {idx + 1}/{len(chunks)}]\n{chunk}"
            raw_json = await self._invoke_with_fallback(prompt, chunk)
            parsed = json.loads(raw_json)
            for k, v in parsed.items():
                if k not in merged or merged[k] in (None, "", []):
                    merged[k] = v
                elif isinstance(merged[k], list) and isinstance(v, list):
                    merged[k].extend(x for x in v if x not in merged[k])
        return merged

    async def _invoke_with_fallback(self, prompt: str, chunk: str) -> str:
        last_error: Optional[Exception] = None
        for tier in self.tiers:
            for attempt in range(self.max_retries_per_tier):
                try:
                    return await tier.handler(prompt, chunk)
                except RateLimitError as exc:
                    last_error = exc
                    backoff = exc.retry_after or min(
                        self.max_delay, self.base_delay * (2**attempt)
                    )
                    jitter = random.uniform(0, backoff * 0.5)
                    logger.warning(
                        "429 on tier=%s attempt=%d; sleeping %.2fs",
                        tier.name,
                        attempt + 1,
                        backoff + jitter,
                    )
                    await asyncio.sleep(backoff + jitter)
                except PayloadTooLargeError as exc:
                    last_error = exc
                    logger.warning("413 on tier=%s; truncating chunk by 35%%", tier.name)
                    chunk = chunk[: int(len(chunk) * 0.65)]
                    prompt = prompt[: int(len(prompt) * 0.65)]
                except Exception as exc:
                    last_error = exc
                    logger.error("Error on tier=%s attempt=%d: %s", tier.name, attempt + 1, exc)
                    break  # Fail over immediately on non-transient tier errors
        raise RuntimeError(f"All LLM tiers exhausted. Last error: {last_error}")

    async def _call_gemini(self, prompt: str, _chunk: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        from google import genai  # type: ignore

        client = genai.Client(api_key=api_key)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return resp.text

    async def _call_groq(self, prompt: str, _chunk: str) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not configured")
        from groq import AsyncGroq  # type: ignore

        client = AsyncGroq(api_key=api_key)
        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or "{}"

    async def _call_deepseek(self, prompt: str, _chunk: str) -> str:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")
        from openai import AsyncOpenAI  # type: ignore

        client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or "{}"

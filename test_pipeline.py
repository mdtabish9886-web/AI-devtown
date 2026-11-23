"""Unit tests for schemas, freshness, 413/429 resilience, and entity resolution."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone

from src.entity_resolver import EntityResolver
from src.freshness import FreshnessTracker, is_within_24h, parse_timestamp
from src.llm_orchestrator import (
    LLMTier,
    MultiTierLLMOrchestrator,
    PayloadTooLargeError,
    RateLimitError,
    chunk_text_semantic,
)
from src.schemas import PricingModel, ProductContent, ProductEntity, SourceRef, StartupContent, StartupEntity


class TestSchemas(unittest.TestCase):
    def test_startup_and_product_schema(self) -> None:
        s = StartupEntity(
            source=SourceRef(name="YC", url="https://www.ycombinator.com/companies/openai"),
            content=StartupContent(entityName="OpenAI"),
        )
        self.assertEqual(s.recordType, "STARTUP")
        self.assertEqual(s.schemaVersion, "1.0")

        p = ProductEntity(
            source=SourceRef(name="ProductHunt", url="https://www.producthunt.com/posts/chatgpt"),
            content=ProductContent(startupName="OpenAI", pricingModel=PricingModel.FREEMIUM),
        )
        self.assertEqual(p.to_dict()["content"]["pricingModel"], "FREEMIUM")


class TestFreshness(unittest.TestCase):
    def test_relative_and_iso_dates(self) -> None:
        now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
        dt_rel = parse_timestamp("2 hours ago", now=now)
        self.assertTrue(is_within_24h(dt_rel, now=now))

        dt_old = parse_timestamp("3 days ago", now=now)
        self.assertFalse(is_within_24h(dt_old, now=now))

        dt_iso = parse_timestamp("2026-11-23T06:00:00Z", now=now)
        self.assertTrue(is_within_24h(dt_iso, now=now))

    def test_undated_content_hash_heuristic(self) -> None:
        tracker = FreshnessTracker()
        now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
        fresh1, _ = tracker.evaluate("https://example.com/news", None, "New AI model released", now=now)
        self.assertTrue(fresh1)

        # Same content 30 hours later -> stale
        later = now + timedelta(hours=30)
        fresh2, _ = tracker.evaluate("https://example.com/news", None, "New AI model released", now=later)
        self.assertFalse(fresh2)


class TestEntityResolution(unittest.TestCase):
    def test_canonical_mapping(self) -> None:
        resolver = EntityResolver()
        for variant in ("OpenAI", "OpenAI, Inc.", "Open AI"):
            canonical, _, _ = resolver.resolve(variant, source_url="https://example.com")
            self.assertEqual(canonical, "OpenAI")
        self.assertEqual(len(resolver.logs), 3)


class TestLLMOrchestrator(unittest.TestCase):
    def test_semantic_chunking_prevents_413(self) -> None:
        text = "\n".join([f"Paragraph {i}: " + ("x" * 100) for i in range(50)])
        chunks = chunk_text_semantic(text, max_chars=1000, overlap_chars=100)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))

    def test_429_and_413_tier_fallback(self) -> None:
        calls = []

        async def tier1(_prompt: str, _chunk: str) -> str:
            calls.append("tier1")
            raise RateLimitError("429 Too Many Requests", retry_after=0.01)

        async def tier2(_prompt: str, _chunk: str) -> str:
            calls.append("tier2")
            raise PayloadTooLargeError("413 Payload Too Large")

        async def tier3(_prompt: str, _chunk: str) -> str:
            calls.append("tier3")
            return json.dumps({"entityName": "Anthropic", "pricingModel": "FREEMIUM"})

        orch = MultiTierLLMOrchestrator(
            tiers=[
                LLMTier("gemini", "flash", tier1),
                LLMTier("groq", "llama3", tier2),
                LLMTier("deepseek", "v3", tier3),
            ],
            max_retries_per_tier=2,
            base_delay=0.01,
        )
        result = asyncio.run(orch.extract_structured("Anthropic Claude", "Extract JSON"))
        self.assertEqual(result["entityName"], "Anthropic")
        self.assertIn("tier1", calls)
        self.assertIn("tier3", calls)


if __name__ == "__main__":
    unittest.main()

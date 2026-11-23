"""Deterministic entity resolution against a 50-startup canonical seed registry."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from src.schemas import EntityMappingLogEntry

SEED_CANONICAL_STARTUPS: List[str] = [
    "OpenAI",
    "Anthropic",
    "Google DeepMind",
    "Mistral AI",
    "Cohere",
    "Perplexity AI",
    "Hugging Face",
    "Scale AI",
    "Databricks",
    "Cursor",
    "Midjourney",
    "Runway",
    "ElevenLabs",
    "Stability AI",
    "Inflection AI",
    "Character.AI",
    "Adept",
    "Together AI",
    "Fireworks AI",
    "Groq",
    "Cerebras",
    "SambaNova",
    "Weights & Biases",
    "LangChain",
    "LlamaIndex",
    "Pinecone",
    "Weaviate",
    "Qdrant",
    "Chroma",
    "Modal",
    "Replicate",
    "Anyscale",
    "Glean",
    "Harvey",
    "Hebbia",
    "Sierra",
    "Cognition AI",
    "Poolside",
    "Magic",
    "Sakana AI",
    "xAI",
    "Figure AI",
    "Physical Intelligence",
    "Wayve",
    "Synthesia",
    "HeyGen",
    "Pika",
    "Suno",
    "Writer",
    "Abridge",
]

MANUAL_ALIASES: Dict[str, str] = {
    "anysphere": "Cursor",
    "devin": "Cognition AI",
    "deepmind": "Google DeepMind",
    "wandb": "Weights & Biases",
    "huggingface": "Hugging Face",
    "openai lp": "OpenAI",
    "anthropic pbc": "Anthropic",
    "x.ai": "xAI",
}

LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|pbc|lp|plc|sas|ag|pty)\b\.?",
    re.IGNORECASE,
)


def normalize_key(name: str) -> str:
    cleaned = LEGAL_SUFFIX_RE.sub("", name.lower())
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned)
    return cleaned.strip()


class EntityResolver:
    """Canonicalizes noisy startup and product strings and logs all mappings."""

    def __init__(
        self,
        seed_entities: Optional[List[str]] = None,
        fuzzy_threshold: float = 0.86,
    ) -> None:
        self.seeds = seed_entities or SEED_CANONICAL_STARTUPS
        self.fuzzy_threshold = fuzzy_threshold
        self._key_to_canonical: Dict[str, str] = {}
        self.logs: List[EntityMappingLogEntry] = []

        for canonical in self.seeds:
            self._key_to_canonical[normalize_key(canonical)] = canonical
        for alias, canonical in MANUAL_ALIASES.items():
            self._key_to_canonical[normalize_key(alias)] = canonical

    def resolve(self, raw_name: str, source_url: str = "") -> Tuple[str, str, float]:
        """Resolve raw_name to (canonical_name, match_method, confidence)."""
        raw_clean = " ".join(raw_name.split()).strip()
        if not raw_clean:
            return raw_name, "EMPTY", 0.0

        # 1. Exact case-insensitive match
        for canonical in self.seeds:
            if raw_clean.lower() == canonical.lower():
                self._record(raw_clean, canonical, "EXACT", 1.0, source_url)
                return canonical, "EXACT", 1.0

        # 2. Normalized key / legal-suffix stripped match
        key = normalize_key(raw_clean)
        if key in self._key_to_canonical:
            canonical = self._key_to_canonical[key]
            self._record(raw_clean, canonical, "NORMALIZED_KEY", 0.98, source_url)
            return canonical, "NORMALIZED_KEY", 0.98

        # 3. Fuzzy similarity against canonical keys
        best_score = 0.0
        best_canonical: Optional[str] = None
        for seed_key, canonical in self._key_to_canonical.items():
            score = SequenceMatcher(None, key, seed_key).ratio()
            if score > best_score:
                best_score = score
                best_canonical = canonical

        if best_canonical and best_score >= self.fuzzy_threshold:
            self._record(raw_clean, best_canonical, "FUZZY", best_score, source_url)
            return best_canonical, "FUZZY", best_score

        # 4. Unmatched -> keep cleaned title-preserved string as new canonical
        self._record(raw_clean, raw_clean, "NEW_CANONICAL", 1.0, source_url)
        return raw_clean, "NEW_CANONICAL", 1.0

    def _record(
        self,
        raw_name: str,
        canonical_name: str,
        method: str,
        confidence: float,
        source_url: str,
    ) -> None:
        self.logs.append(
            EntityMappingLogEntry(
                raw_name=raw_name,
                canonical_name=canonical_name,
                match_method=method,
                confidence=confidence,
                source_url=source_url,
            )
        )

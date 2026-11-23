"""Date normalization, 24-hour freshness filtering, and content-hash heuristics."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional, Tuple


RELATIVE_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>s|sec|secs|second|seconds|m|min|mins|minute|minutes|"
    r"h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks)\s*ago",
    re.IGNORECASE,
)


def parse_timestamp(raw: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse ISO-8601, RFC-2822, common date strings, and relative expressions to UTC datetime."""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    ref = now or datetime.now(timezone.utc)
    lower = text.lower()

    if lower in {"just now", "moments ago", "today", "new"}:
        return ref
    if lower == "yesterday":
        return ref - timedelta(days=1)

    rel_match = RELATIVE_RE.search(lower)
    if rel_match:
        val = int(rel_match.group("value"))
        unit = rel_match.group("unit")[0]
        if unit == "s":
            return ref - timedelta(seconds=val)
        if unit == "m":
            return ref - timedelta(minutes=val)
        if unit == "h":
            return ref - timedelta(hours=val)
        if unit == "d":
            return ref - timedelta(days=val)
        if unit == "w":
            return ref - timedelta(weeks=val)

    # ISO-8601 (handling trailing Z)
    iso_candidate = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # RFC-2822 (RSS/Atom pubDate)
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    # Common human formats
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def normalize_to_iso(raw: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    dt = parse_timestamp(raw, now=now)
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def is_within_24h(dt: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if dt is None:
        return False
    ref = now or datetime.now(timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    delta = ref - dt_utc
    return timedelta(seconds=0) <= delta <= timedelta(hours=24)


class FreshnessTracker:
    """Tracks seen URLs, ETags, and SHA-256 content hashes for undated sources."""

    def __init__(self) -> None:
        self._url_hashes: Dict[str, str] = {}
        self._seen_first_at: Dict[str, datetime] = {}

    @staticmethod
    def compute_content_hash(text: str) -> str:
        normalized = " ".join(text.split()).encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()

    def evaluate(
        self,
        url: str,
        raw_date: Optional[str],
        content_text: str,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """Return (is_fresh_24h, resolved_iso_timestamp)."""
        ref = now or datetime.now(timezone.utc)
        parsed = parse_timestamp(raw_date, now=ref)
        if parsed is not None:
            return is_within_24h(parsed, now=ref), parsed.astimezone(timezone.utc).isoformat()

        # Heuristic for undated pages: new or changed content hash since last run
        digest = self.compute_content_hash(content_text)
        prev_hash = self._url_hashes.get(url)
        if prev_hash != digest:
            self._url_hashes[url] = digest
            self._seen_first_at[url] = ref
            return True, ref.astimezone(timezone.utc).isoformat()

        first_seen = self._seen_first_at[url]
        return is_within_24h(first_seen, now=ref), first_seen.astimezone(timezone.utc).isoformat()

"""Canonical data schemas for GraphOne / FrontierAtlas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


@dataclass
class SourceRef:
    name: str
    url: str


@dataclass
class StartupContentData:
    employeeCount: Optional[int] = None


@dataclass
class StartupContent:
    entityName: str
    data: StartupContentData = field(default_factory=StartupContentData)


@dataclass
class StartupEntity:
    source: SourceRef
    content: StartupContent
    schemaVersion: str = "1.0"
    recordType: str = "STARTUP"
    collectedAt: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sheet_row(self) -> List[Any]:
        return [
            self.schemaVersion,
            self.recordType,
            self.source.name,
            self.source.url,
            self.content.entityName,
            self.content.data.employeeCount if self.content.data.employeeCount is not None else "",
            self.collectedAt,
        ]


@dataclass
class ProductContent:
    startupName: str
    pricingModel: PricingModel
    productName: Optional[str] = None


@dataclass
class ProductEntity:
    source: SourceRef
    content: ProductContent
    schemaVersion: str = "1.0"
    recordType: str = "PRODUCT"
    collectedAt: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["content"]["pricingModel"] = self.content.pricingModel.value
        return d

    def to_sheet_row(self) -> List[Any]:
        return [
            self.schemaVersion,
            self.recordType,
            self.source.name,
            self.source.url,
            self.content.startupName,
            self.content.pricingModel.value,
            self.collectedAt,
        ]


@dataclass
class ResearchPaperContent:
    title: str
    authors: List[str]
    paper_url: str
    github_url: Optional[str]
    github_stars: Optional[int]
    published_date: str


@dataclass
class ResearchPaperEntity:
    content: ResearchPaperContent
    schemaVersion: str = "1.0"
    recordType: str = "RESEARCH_PAPER"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sheet_row(self) -> List[Any]:
        return [
            self.schemaVersion,
            self.recordType,
            self.content.title,
            ", ".join(self.content.authors),
            self.content.paper_url,
            self.content.github_url or "",
            self.content.github_stars if self.content.github_stars is not None else "",
            self.content.published_date,
        ]


@dataclass
class JobContent:
    company: str
    date: str
    is_remote: bool
    role_family: str
    title: str = ""
    url: str = ""


@dataclass
class JobEntity:
    content: JobContent
    schemaVersion: str = "1.0"
    recordType: str = "JOB"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sheet_row(self) -> List[Any]:
        return [
            self.schemaVersion,
            self.recordType,
            self.content.company,
            self.content.date,
            self.content.is_remote,
            self.content.role_family,
            self.content.title,
            self.content.url,
        ]


@dataclass
class NewsContent:
    title: str
    published_date: str
    summary: str
    full_text_excerpt: str


@dataclass
class NewsEntity:
    source: SourceRef
    content: NewsContent
    schemaVersion: str = "1.0"
    recordType: str = "NEWS"
    collectedAt: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sheet_row(self) -> List[Any]:
        return [
            self.schemaVersion,
            self.recordType,
            self.source.name,
            self.source.url,
            self.content.title,
            self.content.published_date,
            self.content.summary,
            self.collectedAt,
        ]


@dataclass
class EntityMappingLogEntry:
    raw_name: str
    canonical_name: str
    match_method: str
    confidence: float
    source_url: str
    logged_at: str = field(default_factory=utc_now_iso)

    def to_sheet_row(self) -> List[Any]:
        return [
            self.raw_name,
            self.canonical_name,
            self.match_method,
            round(self.confidence, 4),
            self.source_url,
            self.logged_at,
        ]

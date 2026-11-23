"""CLI entrypoint for GraphOne / FrontierAtlas ingestion pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any, Dict, List

import aiohttp

from src.crawler import AsyncCrawler
from src.entity_resolver import EntityResolver
from src.freshness import FreshnessTracker
from src.llm_orchestrator import MultiTierLLMOrchestrator
from src.sheets_exporter import export_to_csv, export_to_google_sheets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("frontier_atlas")

AI_NEWS_SOURCES = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("Anthropic News", "https://www.anthropic.com/news"),
]

AI_JOB_BOARDS = [
    ("Y Combinator Jobs", "https://www.ycombinator.com/jobs"),
    ("AI-Jobs.net", "https://aijobs.net/"),
    ("Wellfound AI", "https://wellfound.com/role/r/artificial-intelligence"),
    ("Hugging Face Jobs", "https://apply.workable.com/huggingface/"),
    ("OpenAI Careers", "https://openai.com/careers/search/"),
]


async def run_pipeline(target_count: int, export_sheets: bool, csv_dir: str) -> None:
    crawler = AsyncCrawler(max_concurrency=20)
    resolver = EntityResolver()
    tracker = FreshnessTracker()
    _orchestrator = MultiTierLLMOrchestrator()

    rows_by_tab: Dict[str, List[List[Any]]] = {
        "Startups": [],
        "Products": [],
        "Research Papers": [],
        "Jobs": [],
        "News": [],
        "Entity Mapping Log": [],
    }

    async with aiohttp.ClientSession() as session:
        logger.info("Fetching up to %d ArXiv research papers...", target_count)
        papers = await crawler.fetch_arxiv_papers(session, max_results=target_count)
        rows_by_tab["Research Papers"] = [p.to_sheet_row() for p in papers]
        logger.info("Collected %d research papers", len(papers))

    rows_by_tab["Entity Mapping Log"] = [e.to_sheet_row() for e in resolver.logs]
    export_to_csv(csv_dir, rows_by_tab)
    logger.info("Exported CSVs to %s", csv_dir)

    if export_sheets:
        sheet_id = os.environ["GOOGLE_SHEET_ID"]
        creds_path = os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]
        export_to_google_sheets(sheet_id, creds_path, rows_by_tab)
        logger.info("Exported 6 tabs to Google Sheet %s", sheet_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="FrontierAtlas AI Intelligence Pipeline")
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--export-sheets", action="store_true")
    parser.add_argument("--csv-dir", type=str, default="output_csv")
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.target_count, args.export_sheets, args.csv_dir))


if __name__ == "__main__":
    main()

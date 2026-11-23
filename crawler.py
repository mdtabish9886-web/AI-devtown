"""Async web crawler with aiohttp + Playwright stealth fallback and GitHub star lookup."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from src.schemas import ResearchPaperContent, ResearchPaperEntity

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

GITHUB_REPO_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


class AsyncCrawler:
    """High-concurrency async crawler with Cloudflare/JS Playwright fallback."""

    def __init__(self, max_concurrency: int = 20, request_timeout: int = 20) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.timeout = aiohttp.ClientTimeout(total=request_timeout)
        self.github_token = os.getenv("GITHUB_TOKEN")

    async def fetch_html(
        self,
        session: aiohttp.ClientSession,
        url: str,
        use_playwright_on_block: bool = True,
    ) -> str:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        async with self.semaphore:
            async with session.get(url, headers=headers, timeout=self.timeout) as resp:
                if resp.status in (403, 429, 503) and use_playwright_on_block:
                    logger.info("HTTP %d on %s; escalating to Playwright stealth", resp.status, url)
                    return await self.fetch_with_playwright(url)
                resp.raise_for_status()
                return await resp.text()

    async def fetch_with_playwright(self, url: str) -> str:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1366, "height": 768},
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            content = await page.content()
            await browser.close()
            return content

    async def fetch_github_stars(
        self, session: aiohttp.ClientSession, github_url: Optional[str]
    ) -> Optional[int]:
        if not github_url:
            return None
        match = GITHUB_REPO_RE.search(github_url)
        if not match:
            return None
        owner, repo = match.group(1), match.group(2).rstrip(".git")
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        async with self.semaphore:
            async with session.get(api_url, headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("stargazers_count")

    async def fetch_arxiv_papers(
        self,
        session: aiohttp.ClientSession,
        query: str = "cat:cs.AI OR cat:cs.LG",
        max_results: int = 1000,
        batch_size: int = 100,
    ) -> List[ResearchPaperEntity]:
        """Fetch ArXiv papers in paginated batches and correlate GitHub stars."""
        papers: List[ResearchPaperEntity] = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for start in range(0, max_results, batch_size):
            url = (
                f"http://export.arxiv.org/api/query?search_query={query}"
                f"&start={start}&max_results={min(batch_size, max_results - start)}"
                f"&sortBy=submittedDate&sortOrder=descending"
            )
            xml_text = await self.fetch_html(session, url, use_playwright_on_block=False)
            root = ET.fromstring(xml_text)

            for entry in root.findall("atom:entry", ns):
                title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
                paper_url = (entry.findtext("atom:id", "", ns) or "").strip()
                published = (entry.findtext("atom:published", "", ns) or "").strip()
                summary = entry.findtext("atom:summary", "", ns) or ""
                authors = [
                    (a.findtext("atom:name", "", ns) or "").strip()
                    for a in entry.findall("atom:author", ns)
                ]
                gh_match = GITHUB_REPO_RE.search(summary)
                gh_url = gh_match.group(0) if gh_match else None
                stars = await self.fetch_github_stars(session, gh_url) if gh_url else None

                papers.append(
                    ResearchPaperEntity(
                        content=ResearchPaperContent(
                            title=title,
                            authors=authors,
                            paper_url=paper_url,
                            github_url=gh_url,
                            github_stars=stars,
                            published_date=published,
                        )
                    )
                )
        return papers

    @staticmethod
    def extract_pwc_paper_links(html: str) -> Dict[str, Any]:
        """Extract title, paper URL, and GitHub URL from a Papers with Code page."""
        soup = BeautifulSoup(html, "html.parser")
        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else ""
        gh_match = GITHUB_REPO_RE.search(html)
        return {
            "title": title,
            "github_url": gh_match.group(0) if gh_match else None,
        }

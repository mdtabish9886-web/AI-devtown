# GraphOne / FrontierAtlas — AI Intelligence Ingestion Pipeline

A scalable, fault-tolerant asynchronous data acquisition, 24-hour freshness filtering, multi-tier LLM extraction, and deterministic entity resolution pipeline for the AI & venture ecosystem.

## Repository Structure

```text
frontier-atlas-pipeline/
├── README.md
├── requirements.txt
├── .env.example
├── architecture.pdf          # (Included separately / copy into repo root)
├── src/
│   ├── __init__.py
│   ├── schemas.py            # Canonical JSON/dataclass schemas (Startup, Product, Paper, Job, News)
│   ├── freshness.py          # Date normalization, 24h filter, and content-hash heuristics
│   ├── entity_resolver.py    # 50-startup seed canonicalizer & Entity Mapping Log generator
│   ├── llm_orchestrator.py   # Gemini Flash -> Groq Llama 3 -> DeepSeek fallback, 413 chunker, 429 backoff
│   ├── crawler.py            # Async aiohttp + Playwright stealth crawler (ArXiv, PwC, GitHub, News, Jobs)
│   ├── sheets_exporter.py    # 6-tab Google Sheets exporter (gspread) + CSV fallback
│   └── main.py               # End-to-end async pipeline entrypoint
└── tests/
    └── test_pipeline.py      # Unit tests for schemas, freshness, 413/429 handling, and entity resolution
```

## Setup Instructions

1. **Create a virtual environment & install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   Populate `.env` with:
   - `GEMINI_API_KEY` (Primary LLM tier: Gemini 2.5 Flash)
   - `GROQ_API_KEY` (Secondary LLM tier: Llama 3.3 70B)
   - `DEEPSEEK_API_KEY` (Tertiary LLM tier: DeepSeek-V3)
   - `GITHUB_TOKEN` (Increases GitHub REST API rate limit from 60 to 5,000 req/hr for star counts)
   - `GOOGLE_SHEETS_CREDENTIALS_JSON` (Path to Google Service Account JSON)
   - `GOOGLE_SHEET_ID` (Target Google Sheet ID with the 6 required tabs)

3. **Run unit tests**
   ```bash
   python3 -m pytest tests/ -v
   # or: python3 -m unittest discover -s tests -v
   ```

4. **Run the live ingestion pipeline**
   ```bash
   python3 -m src.main --target-count 1000 --export-sheets
   ```

## Architecture Overview

1. **Async Acquisition (`src/crawler.py`)**: Uses `asyncio` + `aiohttp` with per-domain token-bucket rate limiting and semaphore concurrency, escalating to `playwright.async_api` stealth contexts for Cloudflare/Datadome or JS-rendered pages.
2. **24-Hour Freshness (`src/freshness.py`)**: Normalizes ISO-8601, RFC-2822, and relative timestamps (`"2 hours ago"`, `"yesterday"`), falling back to SHA-256 content-hash + `ETag` diffing when metadata is absent.
3. **Multi-Tier LLM Extraction (`src/llm_orchestrator.py`)**: Strips boilerplate HTML, performs semantic section-aware chunking to prevent `413 Payload Too Large`, and routes through **Gemini Flash -> Groq Llama 3 -> DeepSeek** with exponential backoff + full jitter on `429 Too Many Requests`.
4. **Deterministic Entity Resolution (`src/entity_resolver.py`)**: Strips legal suffixes, normalizes punctuation/whitespace, and resolves entities against a 50-startup canonical seed registry with fuzzy token-ratio fallback, logging every decision to `Entity Mapping Log`.

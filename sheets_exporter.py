"""Google Sheets 6-tab exporter with CSV fallback."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, List

TAB_HEADERS: Dict[str, List[str]] = {
    "Startups": [
        "schemaVersion",
        "recordType",
        "source.name",
        "source.url",
        "content.entityName",
        "content.data.employeeCount",
        "collectedAt",
    ],
    "Products": [
        "schemaVersion",
        "recordType",
        "source.name",
        "source.url",
        "content.startupName",
        "content.pricingModel",
        "collectedAt",
    ],
    "Research Papers": [
        "schemaVersion",
        "recordType",
        "content.title",
        "content.authors",
        "content.paper_url",
        "content.github_url",
        "content.github_stars",
        "content.published_date",
    ],
    "Jobs": [
        "schemaVersion",
        "recordType",
        "content.company",
        "content.date",
        "content.is_remote",
        "content.role_family",
        "content.title",
        "source.url",
    ],
    "News": [
        "schemaVersion",
        "recordType",
        "source.name",
        "source.url",
        "content.title",
        "content.published_date",
        "content.summary",
        "collectedAt",
    ],
    "Entity Mapping Log": [
        "raw_name",
        "canonical_name",
        "match_method",
        "confidence",
        "source_url",
        "logged_at",
    ],
}


def export_to_csv(output_dir: str, rows_by_tab: Dict[str, List[List[Any]]]) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for tab_name, headers in TAB_HEADERS.items():
        filename = tab_name.lower().replace(" ", "_") + ".csv"
        with open(out / filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows_by_tab.get(tab_name, []))


def export_to_google_sheets(
    sheet_id: str,
    credentials_json: str,
    rows_by_tab: Dict[str, List[List[Any]]],
) -> None:
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(credentials_json, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)

    for tab_name, headers in TAB_HEADERS.items():
        try:
            ws = spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=tab_name, rows=2000, cols=len(headers))
        ws.clear()
        payload = [headers] + rows_by_tab.get(tab_name, [])
        ws.update("A1", payload, value_input_option="USER_ENTERED")

#!/usr/bin/env python3
"""
LLM Data Fetcher Script for GitHub Actions
Fetches data from Artificial Analysis API and stores it in date-organized folders.

Endpoint
    The legacy path ``/api/v2/data/llms/models`` was retired on 4 Nov 2026 and
    now returns HTTP 410. Its replacements are documented at
    https://artificialanalysis.ai/data-api/migrate-v2-data:

    - Free, any valid key: ``GET /api/v2/language/models/free``
    - Pro or Commercial only: ``GET /api/v2/language/models``

    This repository has no Pro subscription. The Pro URL returns HTTP 403 for
    the existing key, so the script calls the free URL. The same
    ``x-api-key`` header is still used. A new key is not required.

Response schema
    The body no longer includes ``status`` or ``prompt_options``. A successful
    list response contains ``tier``, ``intelligence_index_version``,
    ``pagination`` (``page``, ``page_size``, ``total_pages``, ``has_more``),
    and ``data`` (the model array). Results are paginated, so every page is
    fetched and combined before anything is written. ``data/YYYY-MM-DD/llm_data.json``
    still stores one object whose ``data`` field is the full model list.

    The free endpoint's only documented query parameter is ``page``. It does
    not accept ``prompt_type``. Each model includes the public subset: headline
    and capability indexes, input/output pricing, median performance, and
    Performance v3 headline means. Pro-only fields such as blended pricing,
    percentiles, and per-benchmark scores are omitted. Metadata keeps
    ``api_status`` as the HTTP status and sets ``prompt_options`` and
    ``prompt_type`` to null.
"""

import os
import json
import requests
from datetime import datetime
import sys
from pathlib import Path

API_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
MAX_PAGES = 100


class ApiResponseError(Exception):
    """Raised when a response cannot be stored safely."""


def fetch_llm_data(api_key: str) -> tuple:
    """Fetch every page of LLM data. Returns (http_status, combined_payload)."""
    pages = []
    http_status = None

    for page in range(1, MAX_PAGES + 1):
        http_status, payload = fetch_page(api_key, page)
        pages.append(payload)
        try:
            has_more = page_has_more(payload, page)
        except ApiResponseError as exc:
            print(f"Error fetching data: {exc}")
            sys.exit(1)
        if not has_more:
            break
    else:
        print("Error fetching data: pagination did not finish within the page limit")
        sys.exit(1)

    try:
        combined = combine_pages(pages)
    except ApiResponseError as exc:
        print(f"Error fetching data: {exc}")
        sys.exit(1)

    return http_status, combined


def fetch_page(api_key: str, page: int) -> tuple:
    """Request one page. Errors are reported without the API key or response body."""
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }
    params = {"page": page}

    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        report_request_error(exc)
        sys.exit(1)

    try:
        payload = response.json()
    except ValueError:
        print(f"Error fetching data: HTTP {response.status_code} response was not JSON")
        sys.exit(1)

    if not isinstance(payload, dict):
        print("Error fetching data: response JSON was not an object")
        sys.exit(1)

    return response.status_code, payload


def report_request_error(exc: requests.exceptions.RequestException) -> None:
    """Print a status-only failure. Never include headers, the key, or the body."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 401:
        detail = "API key was rejected or missing"
    elif status == 403:
        detail = "API key tier cannot access this endpoint"
    elif status is not None:
        detail = "request was not successful"
    else:
        detail = f"request failed ({type(exc).__name__})"
        print(f"Error fetching data: {detail}")
        return

    print(f"Error fetching data: HTTP {status} from {API_URL} ({detail})")


def page_has_more(payload: dict, expected_page: int) -> bool:
    """Validate one page envelope and return whether another page must be fetched."""
    data = payload.get("data")
    pagination = payload.get("pagination")
    if not isinstance(data, list) or not isinstance(pagination, dict):
        raise ApiResponseError("response missing data list or pagination object")
    if not data:
        raise ApiResponseError(f"page {expected_page} returned no models")

    page = pagination.get("page")
    total_pages = pagination.get("total_pages")
    has_more = pagination.get("has_more")
    if page != expected_page:
        raise ApiResponseError("pagination.page did not match the requested page")
    if not isinstance(total_pages, int) or total_pages < 1 or total_pages > MAX_PAGES:
        raise ApiResponseError("pagination.total_pages was missing or out of range")
    if expected_page > total_pages:
        raise ApiResponseError("requested page exceeded pagination.total_pages")
    if not isinstance(has_more, bool):
        raise ApiResponseError("pagination.has_more was missing or not a boolean")
    if has_more and expected_page >= total_pages:
        raise ApiResponseError("pagination.has_more was true on the last page")
    if not has_more and expected_page != total_pages:
        raise ApiResponseError("pagination ended before total_pages")
    return has_more


def combine_pages(pages: list) -> dict:
    """Merge validated pages into one document. Refuses an empty model list."""
    if not pages:
        raise ApiResponseError("no pages were returned")

    first = pages[0]
    first_pagination = first.get("pagination")
    if not isinstance(first_pagination, dict):
        raise ApiResponseError("response missing pagination object")

    total_pages = first_pagination.get("total_pages")
    page_size = first_pagination.get("page_size")
    if len(pages) != total_pages:
        raise ApiResponseError("fetched page count did not match pagination.total_pages")
    if not isinstance(page_size, int) or page_size < 1:
        raise ApiResponseError("pagination.page_size was missing or invalid")

    models = []
    for index, payload in enumerate(pages, start=1):
        page_has_more(payload, index)
        pagination = payload["pagination"]
        if pagination.get("total_pages") != total_pages or pagination.get("page_size") != page_size:
            raise ApiResponseError("pagination fields changed between pages")
        if payload.get("tier") != first.get("tier"):
            raise ApiResponseError("tier changed between pages")
        if payload.get("intelligence_index_version") != first.get("intelligence_index_version"):
            raise ApiResponseError("intelligence_index_version changed between pages")
        models.extend(payload["data"])

    if not models:
        raise ApiResponseError("API returned no models")

    return {
        "tier": first.get("tier"),
        "intelligence_index_version": first.get("intelligence_index_version"),
        "prompt_type": None,
        "pagination": {
            "page_size": page_size,
            "total_pages": total_pages,
            "pages_fetched": len(pages),
        },
        "data": models,
    }


def save_data_to_file(data: dict, date_str: str, http_status: int) -> None:
    """Save data to date-organized folder structure."""
    models = data.get("data")
    if http_status != 200 or not isinstance(models, list) or not models:
        print("Error: refusing to write empty or invalid model data")
        sys.exit(1)

    # Create directory structure: data/yyyy-mm-dd/
    data_dir = Path("data") / date_str
    data_dir.mkdir(parents=True, exist_ok=True)

    # Save combined API response
    raw_file = data_dir / "llm_data.json"
    with open(raw_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Body no longer includes status or prompt_options. The free endpoint does
    # not accept prompt_type. api_status is the HTTP status.
    metadata = {
        "fetch_date": date_str,
        "fetch_timestamp": datetime.now().isoformat(),
        "total_models": len(models),
        "api_status": http_status,
        "prompt_options": None,
        "prompt_type": data.get("prompt_type"),
        "tier": data.get("tier"),
        "intelligence_index_version": data.get("intelligence_index_version"),
    }

    metadata_file = data_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Data saved to {data_dir}")
    print(f"Total models: {metadata['total_models']}")


def update_latest_link(date_str: str) -> None:
    """Update latest.json to point to the most recent data"""
    latest_info = {
        "latest_date": date_str,
        "latest_path": f"data/{date_str}/llm_data.json",
        "updated_at": datetime.now().isoformat()
    }

    with open("latest.json", 'w', encoding='utf-8') as f:
        json.dump(latest_info, f, indent=2, ensure_ascii=False)

    print(f"Updated latest.json to point to {date_str}")


def main():
    """Main function"""
    # Get API key from environment variable
    api_key = os.getenv("ARTIFICIAL_ANALYSIS_API_KEY")
    if not api_key:
        print("Error: ARTIFICIAL_ANALYSIS_API_KEY environment variable not set")
        sys.exit(1)

    # Get current date
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Check if data for today already exists
    data_file = Path("data") / current_date / "llm_data.json"
    if data_file.exists():
        print(f"Data for {current_date} already exists. Skipping fetch.")
        return

    print(f"Fetching LLM data for {current_date}...")

    # Fetch data
    http_status, llm_data = fetch_llm_data(api_key)

    # Save data
    save_data_to_file(llm_data, current_date, http_status)

    # Update latest link
    update_latest_link(current_date)

    print("Data fetch completed successfully!")

if __name__ == "__main__":
    main()

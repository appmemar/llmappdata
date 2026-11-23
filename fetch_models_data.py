#!/usr/bin/env python3
"""Fetch the models.dev catalog and publish a models-only daily snapshot.

The upstream catalog contains both ``models`` and ``providers``. The mobile
app needs provider-agnostic model metadata only, so this script intentionally
stores just the ``models`` object in ``v2/YYYY-MM-DD/models_data.json``.
``v2/latest.json`` follows the same pointer pattern as the legacy data feed.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://models.dev/catalog.json?type=all"
OUTPUT_ROOT = Path("v2")


class CatalogResponseError(Exception):
    """Raised when the upstream response is unsafe to publish."""


def fetch_models() -> tuple[int, dict]:
    """Return the HTTP status and the validated models-only object."""
    try:
        request = Request(
            API_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "LLMLeaderBoard-catalog-fetcher/1.0",
            },
        )
        with urlopen(request, timeout=60) as response:
            http_status = response.status
            body = response.read()
    except HTTPError as exc:
        detail = f"HTTP {exc.code}"
        raise CatalogResponseError(f"request failed ({detail})") from exc
    except URLError as exc:
        detail = type(exc.reason).__name__ if isinstance(exc.reason, Exception) else str(exc.reason)
        raise CatalogResponseError(f"request failed ({detail})") from exc

    try:
        catalog = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogResponseError("response was not valid JSON") from exc

    if not isinstance(catalog, dict):
        raise CatalogResponseError("response JSON was not an object")

    models = catalog.get("models")
    if not isinstance(models, dict) or not models:
        raise CatalogResponseError("response did not contain a non-empty models object")

    invalid_ids = [model_id for model_id, model in models.items()
                   if not isinstance(model_id, str) or not isinstance(model, dict)]
    if invalid_ids:
        raise CatalogResponseError("models object contained an invalid entry")

    return http_status, models


def write_snapshot(models: dict, date_str: str, http_status: int) -> None:
    """Write one daily models-only snapshot and its metadata."""
    if http_status != 200 or not models:
        raise CatalogResponseError("refusing to write an empty or unsuccessful response")

    output_dir = OUTPUT_ROOT / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "models_data.json").open("w", encoding="utf-8") as file:
        json.dump(models, file, indent=2, ensure_ascii=False)
        file.write("\n")

    metadata = {
        "fetch_date": date_str,
        "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_models": len(models),
        "api_status": http_status,
        "source_name": "models.dev",
        "source_url": API_URL,
        "source_license": "MIT",
    }
    with (output_dir / "metadata.json").open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)
        file.write("\n")


def update_latest_pointer(date_str: str) -> None:
    """Point mobile clients at the current v2 snapshot."""
    latest = {
        "schema_version": 2,
        "latest_date": date_str,
        "latest_path": f"v2/{date_str}/models_data.json",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_ROOT / "latest.json").open("w", encoding="utf-8") as file:
        json.dump(latest, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main() -> None:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_file = OUTPUT_ROOT / date_str / "models_data.json"
    if data_file.exists():
        print(f"Model catalog for {date_str} already exists. Skipping fetch.")
        return

    print(f"Fetching models.dev catalog for {date_str}...")
    try:
        http_status, models = fetch_models()
        write_snapshot(models, date_str, http_status)
        update_latest_pointer(date_str)
    except CatalogResponseError as exc:
        print(f"Error fetching model catalog: {exc}")
        sys.exit(1)

    print(f"Data saved to {OUTPUT_ROOT / date_str}")
    print(f"Total models: {len(models)}")


if __name__ == "__main__":
    main()

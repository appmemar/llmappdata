#!/usr/bin/env python3
"""
LLM Data Fetcher Script for GitHub Actions
Fetches data from Artificial Analysis API and stores it in date-organized folders
"""

import os
import json
import requests
from datetime import datetime
import sys
from pathlib import Path

def fetch_llm_data(api_key: str) -> dict:
    """Fetch LLM data from Artificial Analysis API"""
    url = "https://artificialanalysis.ai/api/v2/data/llms/models"
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)

def save_data_to_file(data: dict, date_str: str) -> None:
    """Save data to date-organized folder structure"""
    # Create directory structure: data/yyyy-mm-dd/
    data_dir = Path("data") / date_str
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Save raw API response
    raw_file = data_dir / "llm_data.json"
    with open(raw_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Save metadata
    metadata = {
        "fetch_date": date_str,
        "fetch_timestamp": datetime.now().isoformat(),
        "total_models": len(data.get("data", [])),
        "api_status": data.get("status"),
        "prompt_options": data.get("prompt_options")
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
    llm_data = fetch_llm_data(api_key)
    
    # Save data
    save_data_to_file(llm_data, current_date)
    
    # Update latest link
    update_latest_link(current_date)
    
    print("Data fetch completed successfully!")

if __name__ == "__main__":
    main()
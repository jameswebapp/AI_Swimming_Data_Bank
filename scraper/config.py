"""
Configuration for the Maryland Swimming meet scraper.
"""
import os

# Base paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PARSED_DIR = os.path.join(DATA_DIR, "parsed")
MANIFEST_DIR = os.path.join(DATA_DIR, "manifests")

# Maryland Swimming GoMotion URLs
GOMOTION_BASE_URL = "https://www.gomotionapp.com"

# Meet schedule pages by season
SEASON_PAGES = {
    "2023-2024": "https://www.gomotionapp.com/team/md/page/system/res/186916",
    "2024-2025": "https://www.gomotionapp.com/team/md/page/system/res/210811",
    "2025-2026": "https://www.gomotionapp.com/team/md/page/system/res/210812",
    "2026-2027": "https://www.gomotionapp.com/team/md/page/system/res/221132"
}

# Scraper settings
REQUEST_DELAY_SECONDS = 1.0  # Rate limit: 1 request per second
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0  # Exponential backoff: 2s, 4s, 8s

# User-Agent to identify ourselves politely
USER_AGENT = (
    "SwimmingDataBank/1.0 "
    "(Personal swimming analytics project; contact: swimming-data-bank@example.com)"
)

# File type priorities when extracting ZIPs (prefer HY3 > CL2 > SD3)
RESULT_FILE_EXTENSIONS = [".hy3", ".cl2", ".sd3"]

# Ensure directories exist
for d in [DATA_DIR, RAW_DIR, PARSED_DIR, MANIFEST_DIR]:
    os.makedirs(d, exist_ok=True)

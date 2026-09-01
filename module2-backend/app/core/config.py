import os
from pathlib import Path

from dotenv import load_dotenv

# Go from app/core/config.py up to the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Read variables from.env
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
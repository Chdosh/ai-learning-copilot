from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DB_PATH = DATA_DIR / "app.db"
VENDOR_DIR = PROJECT_DIR / "vendor"
VENDOR_TESSERACT_DIR = VENDOR_DIR / "tesseract"
VENDOR_TESSERACT_EXE = VENDOR_TESSERACT_DIR / "tesseract.exe"
VENDOR_TESSDATA_DIR = VENDOR_TESSERACT_DIR / "tessdata"


def ensure_app_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

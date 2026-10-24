"""Download the real Olist dataset from Kaggle into data/raw/.

Setup once:
  1. kaggle.com -> Settings -> API -> "Create New Token" (downloads kaggle.json)
  2. Put it at ~/.kaggle/kaggle.json  (Windows: C:\\Users\\<you>\\.kaggle\\kaggle.json)
  3. python scripts/download_data.py

Manual alternative: download the zip from
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce and extract the 9 CSVs into data/raw/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402


def main():
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        sys.exit("pip install kaggle  (then add ~/.kaggle/kaggle.json)")
    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(config.KAGGLE_DATASET, path=str(config.RAW_DIR), unzip=True)
    missing = [f for f in config.RAW_FILES.values() if not (config.RAW_DIR / f).exists()]
    print("Downloaded to", config.RAW_DIR, "| missing:", missing or "none")


if __name__ == "__main__":
    main()

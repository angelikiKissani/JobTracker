"""Download the Dataset tab to data/dataset.csv for analysis and training.
Run: python -m jobtracker.export_dataset   
"""

import csv
import os
from pathlib import Path

from . import config, sheets

OUTPUT = Path("data") / "dataset.csv"


def main() -> None:
    spreadsheet_id = (os.environ.get("SPREADSHEET_ID") or "").strip()
    if not spreadsheet_id:
        raise SystemExit("Missing SPREADSHEET_ID (add it as a Codespaces secret).")

    sh = sheets.open_spreadsheet(spreadsheet_id)
    rows = sh.worksheet(config.DATASET_TAB).get_all_values()

    width = len(config.DATASET_HEADERS)
    header, *emails = [row[:width] for row in rows]
    emails = [row for row in emails if row[0]]

    OUTPUT.parent.mkdir(exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(emails)
    print(f"Saved {len(emails)} emails to {OUTPUT}")


if __name__ == "__main__":
    main()
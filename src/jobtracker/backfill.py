import argparse
from collections import Counter

from .  import config, sheets
from .dataset import build_row
from .pipeline import read_credentials
from .mailbox import Mailbox

# read how many days to go back
# log in and open the Dataset tab
# go through the inbox and the Applications folder
# turn each job email into a row
# save and print a summary.



def main(argv: list[str] | None=None) -> None:
    parser = argparse.ArgumentParser(description = __doc__.splitlines()[0])
    parser.add_argument("--days",type = int, default = config.BACKFILL_DAYS, 
                        help = "how many days back to collect (default: %(default)s)")
    args = parser.parse_args(argv)

    user, password, spreadsheet_id = read_credentials()
    sh = sheets.open_spreadsheet(spreadsheet_id)
    dataset = sheets.DatasetSheet.load(sh)
    box = Mailbox(user, password)

    folders = [config.MAILBOX] + ([config.MOVE_TO_FOLDER] if config.MOVE_TO_FOLDER else [])
    labels: Counter = Counter()
    
    for folder in folders:
        uids = box.uids_since(folder, args.days)
        print(f"{folder}: {len(uids)} emails in the last {args.days} days")
        for msg in box.fetch_many(uids):
            row = build_row(msg, folder)
            if row and dataset.add(row):
                labels[row[6]] += 1
    box.logout()

    dataset.save()
    print(f"Added {sum(labels.values())} new rows to the {config.DATASET_TAB} tab:")
    for label in config.LABELS:
        print(f"  {label:<17} {labels[label]}")


if __name__ == "__main__":
    main()
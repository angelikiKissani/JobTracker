"""Reading and writing the Google Sheet.

`Tracker` and `EmailLog` keep the data in memory and write all changes in a
few bulk requests at the end of a run. They can also be built without a
worksheet (`ws=None`), which is how the tests use them.
"""

import json
import os
from datetime import datetime

from . import config
from .extract import same_company
from .parsing import norm, stamp

try:
    import gspread
except ImportError:  # lets the pure logic be imported without gspread
    gspread = None


# --------------------------------------------------------------------------
# Connection helpers
# --------------------------------------------------------------------------
def open_spreadsheet(spreadsheet_id: str):
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit("Missing GOOGLE_SERVICE_ACCOUNT_JSON secret.")
    client = gspread.service_account_from_dict(json.loads(raw))
    return client.open_by_key(spreadsheet_id)


def optional_tab(sh, name: str):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return None


# --------------------------------------------------------------------------
# Run state (which emails have been processed), kept in a hidden tab
# --------------------------------------------------------------------------
def load_state(sh):
    ws = optional_tab(sh, config.STATE_TAB)
    if ws is None:
        ws = sh.add_worksheet(title=config.STATE_TAB, rows=5, cols=2)
        try:
            ws.hide()
        except Exception:
            pass
    values = {r[0]: r[1] for r in ws.get_all_values() if len(r) >= 2}
    return ws, values


def save_state(ws, last_uid: int, uidvalidity: str) -> None:
    ws.update(range_name="A1",
              values=[["last_uid", str(last_uid)], ["uidvalidity", uidvalidity]])


# --------------------------------------------------------------------------
# Tracker tab
# --------------------------------------------------------------------------
class Tracker:
    """The Tracker tab, loaded once and edited in memory."""

    def __init__(self, rows: list[list[str]], ws=None, history_ws=None, mirror_ws=None):
        self.ws, self.history_ws, self.mirror_ws = ws, history_ws, mirror_ws
        self.rows = [list(r) for r in rows] or [[]]
        header = [h.strip() for h in self.rows[0]]

        self.col: dict[str, int] = {}
        for key, name in config.COLUMNS.items():
            if name not in header:
                raise SystemExit(f'Column "{name}" not found in the {config.SHEET_NAME} tab.')
            self.col[key] = header.index(name)
        for key, name in config.OPTIONAL_COLUMNS.items():
            if name in header:
                self.col[key] = header.index(name)
        self.people_cols = [header.index(c) for c in config.PEOPLE_COLUMNS if c in header]

        self.width = max(len(r) for r in self.rows)
        for row in self.rows:
            row.extend([""] * (self.width - len(row)))

        self.changes: dict[tuple[int, int], str] = {}  # (row, col) 1-based -> value
        self.mirror: dict[tuple[int, int], str] = {}   # same, for _StatusTracker
        self.history: list[list[str]] = []             # rows for StatusHistory

    @classmethod
    def load(cls, sh) -> "Tracker":
        ws = sh.worksheet(config.SHEET_NAME)
        return cls(ws.get_all_values(), ws,
                   optional_tab(sh, config.HISTORY_TAB),
                   optional_tab(sh, config.MIRROR_TAB))

    # ---- reading ----
    def has(self, key: str) -> bool:
        return key in self.col

    def get(self, r: int, key: str) -> str:
        return self.rows[r][self.col[key]].strip()

    def is_blank(self, r: int) -> bool:
        return not self.get(r, "company") and not self.get(r, "role")

    def known_jobs(self) -> list[str]:
        return [f"{self.get(r, 'company')} | {self.get(r, 'role')} | {self.get(r, 'status')}"
                for r in range(1, len(self.rows)) if not self.is_blank(r)]

    def find_row(self, company: str, role: str | None) -> int | None:
        """Most recent row for this company (and role, when both are known)."""
        if not norm(company):
            return None
        for r in range(len(self.rows) - 1, 0, -1):
            if same_company(self.get(r, "company"), company):
                existing_role = self.get(r, "role")
                if existing_role == config.PLACEHOLDER_ROLE:
                    existing_role = ""
                if role and existing_role and norm(role) != norm(existing_role):
                    continue
                return r
        return None

    def find_by_person(self, display_name: str, addr: str) -> int | None:
        """Row whose Contact/Interviewer column names this sender."""
        name, addr = norm(display_name), (addr or "").lower()
        for r in range(len(self.rows) - 1, 0, -1):
            for c in self.people_cols:
                cell = self.rows[r][c]
                if not cell.strip():
                    continue
                if (len(name) >= 5 and norm(cell) == name) or (addr and addr in cell.lower()):
                    return r
        return None

    # ---- writing ----
    def set(self, r: int, key: str, value) -> None:
        value = "" if value is None else value
        self.rows[r][self.col[key]] = value
        self.changes[(r + 1, self.col[key] + 1)] = value

    def new_row(self) -> int:
        """First blank row (the template pre-fills rows with 'Pending')."""
        for r in range(1, len(self.rows)):
            if self.is_blank(r):
                return r
        self.rows.append([""] * self.width)
        return len(self.rows) - 1

    def change_status(self, r: int, new_status: str, old_status: str) -> None:
        """Set a status and log it, like the template does for manual edits."""
        self.set(r, "status", new_status)
        company, role = self.get(r, "company"), self.get(r, "role")
        self.history.append([stamp(datetime.now(config.TIMEZONE)), company, role,
                             old_status, new_status])
        for c, v in enumerate([company, role, new_status], start=1):
            self.mirror[(r + 1, c)] = v

    def save(self) -> None:
        if self.ws is None:
            return
        _write_cells(self.ws, self.changes)
        if self.mirror_ws is not None:
            _write_cells(self.mirror_ws, self.mirror)
        if self.history and self.history_ws is not None:
            self.history_ws.append_rows(self.history, value_input_option="USER_ENTERED",
                                        table_range="A1")


def _write_cells(ws, changes: dict[tuple[int, int], str]) -> None:
    if not changes:
        return
    needed = max(r for r, _ in changes)
    if needed > ws.row_count:
        ws.add_rows(needed - ws.row_count)
    cells = [gspread.Cell(r, c, v) for (r, c), v in changes.items()]
    ws.update_cells(cells, value_input_option="USER_ENTERED")


# --------------------------------------------------------------------------
# Emails tab: a copy of every job email
# --------------------------------------------------------------------------
class EmailLog:
    def __init__(self, ws=None, next_row: int = 2, gid: int = 0):
        self.ws, self.next_row, self.gid = ws, next_row, gid
        self.rows: list[list[str]] = []

    @classmethod
    def load(cls, sh) -> "EmailLog":
        ws = optional_tab(sh, config.EMAILS_TAB)
        if ws is None:
            ws = sh.add_worksheet(title=config.EMAILS_TAB, rows=200,
                                  cols=len(config.EMAIL_HEADERS))
            try:
                ws.freeze(rows=1)
            except Exception:
                pass
        header = ws.row_values(1)
        if header[:len(config.EMAIL_HEADERS)] != config.EMAIL_HEADERS:
            if ws.col_count < len(config.EMAIL_HEADERS):
                ws.add_cols(len(config.EMAIL_HEADERS) - ws.col_count)
            ws.update(range_name="A1", values=[config.EMAIL_HEADERS])
        return cls(ws, len(ws.col_values(1)) + 1, ws.id)

    def add(self, values: list[str]) -> int:
        """Queue a row; returns the sheet row number it will be written to."""
        self.rows.append(values)
        return self.next_row + len(self.rows) - 1

    def link(self, r: int) -> str:
        return f'=HYPERLINK("#gid={self.gid}&range=A{r}", "View email")'

    def save(self) -> None:
        if self.ws is None or not self.rows:
            return
        last = self.next_row + len(self.rows) - 1
        if last > self.ws.row_count:
            self.ws.add_rows(last - self.ws.row_count + 100)
        self.ws.update(range_name=f"A{self.next_row}", values=self.rows,
                       value_input_option="RAW")

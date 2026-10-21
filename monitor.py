
import subprocess
from html.parser import HTMLParser

URL = (
    "https://plus.wikitree.com/function/WTCatNavigate/Category.htm"
    "?Category=Brandenburg%2C_Preu%C3%9Fen&Levels=2&Details=Edit"
)

EXCLUDED = {"sonczalla-1", "trtnik-2", "kobus-79"}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table_depth = 0
        self.current_table = None
        self.current_row = None
        self.current_cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table_depth == 0:
                self.current_table = []
            self.table_depth += 1
        elif self.table_depth == 1 and tag == "tr":
            self.current_row = []
        elif (
            self.table_depth == 1
            and tag in ("td", "th")
            and self.current_row is not None
        ):
            self.current_cell = []

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.current_cell is not None:
            self.current_row.append(
                " ".join("".join(self.current_cell).split())
            )
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.current_table.append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.tables.append(self.current_table)
                self.current_table = None


result = subprocess.run(
    [
        "curl", "-L", "--fail", "--silent", "--show-error",
        "--max-time", "45", "-A", "Mozilla/5.0", URL
    ],
    capture_output=True,
    text=True,
    check=True
)

parser = TableParser()
parser.feed(result.stdout)

print("Tables found:", len(parser.tables))

total = 0
matches = []
seen = set()

for table in parser.tables:
    if not table:
        continue

    header = table[0]

    if not any("Last Edit" in cell for cell in header):
        continue

    # The editor is the third column (index 2).
    editor_col = 2

    for row in table[1:]:
        if len(row) <= editor_col:
            continue

        category = row[1].strip()
        editor = row[editor_col].strip()

        # Ignore repeated headers.
        if "Last Edit" in editor:
            continue

        # Avoid counting duplicate category rows.
        if category in seen:
            continue

        seen.add(category)
        total += 1

        if not editor or editor.lower() in EXCLUDED:
            continue

        matches.append((category, editor))

print("Total unique categories:", total)
print("Categories edited by other members:", len(matches))

for category, editor in matches[:30]:
    print(category, "|", editor)

if total < 500:
    raise RuntimeError(
        f"Only {total} categories found; expected approximately 530."
    )

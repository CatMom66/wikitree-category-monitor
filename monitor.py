"""WikiTree+ category snapshot comparison and RSS generator.

First live run creates a baseline without generating historical alerts.
Run --self-test to exercise change detection entirely offline.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

URL = ('https://plus.wikitree.com/function/WTCatNavigate/Category.htm'
       '?Category=Brandenburg%2C_Preu%C3%9Fen&Levels=2&Details=Edit')
EXCLUDED = {'sonczalla-1', 'trtnik-2', 'kobus-79'}
SNAPSHOT = Path('data/brandenburg.json')
FEED = Path('docs/brandenburg.xml')
BASE_URL = 'https://www.wikitree.com/wiki/Category:'


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.depth = 0
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.depth == 0:
                self.table = []
            self.depth += 1
        elif self.depth == 1 and tag == 'tr':
            self.row = []
        elif self.depth == 1 and tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.tables.append(self.table)
                self.table = None


def parse_categories(html):
    parser = TableParser()
    parser.feed(html)
    categories = {}
    for table in parser.tables:
        if not table or not any('Last Edit' in c for c in table[0]):
            continue
        for row in table[1:]:
            if len(row) < 4 or 'Last Edit' in row[2]:
                continue
            category, editor, touched = row[1].strip(), row[2].strip(), row[3].strip()
            if category:
                categories[category] = {'editor': editor, 'touched': touched}
    return categories


def detect_changes(old, new):
    """Return only newly seen or changed categories with non-excluded last editors."""
    events = []
    for category, details in sorted(new.items()):
        before = old.get(category)
        if before == details or details['editor'].lower() in EXCLUDED or not details['editor']:
            continue
        events.append({'category': category, **details})
    return events


def make_rss(events):
    now = datetime.now(timezone.utc)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0"><channel>',
             '<title>WikiTree Brandenburg category edits</title>',
             '<link>' + escape(URL) + '</link>',
             '<description>Changes to Brandenburg categories by non-excluded editors</description>']
    for e in events:
        link = BASE_URL + quote(e['category'], safe=',_')

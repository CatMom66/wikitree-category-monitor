"""WikiTree+ Brandenburg category monitor.

First run creates a baseline without RSS alerts. Subsequent runs compare
category editor and PageTouched values. Run `python monitor.py --self-test`
for deterministic tests that never contact WikiTree+.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

REPORT_URL = (
    'https://plus.wikitree.com/function/WTCatNavigate/Category.htm'
    '?Category=Brandenburg%2C_Preu%C3%9Fen&Levels=2&Details=Edit'
)
EXCLUDED = {'sonczalla-1', 'trtnik-2', 'kobus-79'}
STATE_PATH = Path('data/brandenburg.json')
FEED_PATH = Path('docs/brandenburg.xml')
CATEGORY_URL = 'https://www.wikitree.com/wiki/Category:'


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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
    parser = Tables()
    parser.feed(html)
    categories = {}
    for table in parser.tables:
        if not table:
            continue
        header = [c.lower().replace(' ', '') for c in table[0]]
        # The WikiTree+ Details=Edit report uses columns:
        # Level, LvL, category, Last Edit WikiTreeID, PageTouched, ...
        editor_col = next((i for i, c in enumerate(header) if 'lasteditwikitreeid' in c), None)
        if editor_col is None:
            continue
        category_col = editor_col - 1
        touched_col = editor_col + 1
        if category_col < 0:
            continue
        for row in table[1:]:
            if len(row) <= touched_col:
                continue
            category = row[category_col].strip()
            editor = row[editor_col].strip()
            touched = row[touched_col].strip()
            if not category or category.lower().startswith('category'):
                continue
            categories[category] = {'editor': editor, 'touched': touched}
    return categories


def find_changes(previous, current):
    """Return changed categories whose CURRENT editor is not excluded."""
    events = []
    for category, info in sorted(current.items()):
        if previous.get(category) == info:
            continue
        if not info['editor'] or info['editor'].lower() in EXCLUDED:
            continue
        events.append({'category': category, **info})
    return events


def rss_xml(events):
    now = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0"><channel>',
             '<title>WikiTree Brandenburg category edits</title>',
             f'<link>{escape(REPORT_URL)}</link>',
             '<description>Category changes by non-excluded editors</description>']
    for event in events:
        category = event['category']
        editor = event['editor']
        touched = event['touched']
        url = CATEGORY_URL + quote(category.replace(' ', '_'), safe='_,()')
        guid = f'{category}|{editor}|{touched}'
        parts += ['<item>',
                  f'<title>{escape(category)} - {escape(editor)}</title>',
                  f'<link>{escape(url)}</link>',
                  f'<guid isPermaLink="false">{escape(guid)}</guid>',
                  f'<description>Last editor: {escape(editor)}; PageTouched: {escape(touched)}</description>',
                  f'<pubDate>{now}</pubDate>', '</item>']
    parts.append('</channel></rss>')
    xml = '\n'.join(parts) + '\n'
    ElementTree.fromstring(xml)
    return xml


def retrieve():
    result = subprocess.run(
        ['curl', '-L', '--fail', '--silent', '--show-error', '--max-time', '45',
         '-A', 'Mozilla/5.0', REPORT_URL],
        capture_output=True, text=True, check=True)
    return result.stdout


def self_test():
    original = {'Test,_Brandenburg': {'editor': 'Trtnik-2', 'touched': '20261018'}}
    assert find_changes({}, original) == []
    allowed = {'Test,_Brandenburg': {'editor': 'Example-123', 'touched': '20261021'}}
    assert len(find_changes(original, allowed)) == 1
    excluded = {'Test,_Brandenburg': {'editor': 'Kobus-79', 'touched': '20261022'}}
    assert find_changes(allowed, excluded) == []
    assert find_changes(allowed, allowed) == []
    again = {'Test,_Brandenburg': {'editor': 'Example-123', 'touched': '20261023'}}
    assert len(find_changes(allowed, again)) == 1
    xml = rss_xml(find_changes(original, allowed))
    assert len(ElementTree.fromstring(xml).findall('./channel/item')) == 1
    # Test table parsing, including two separate tables and exclusions.
    html = ('<table><tr><th>Level</th><th>LvL</th><th>Category</th>'
            '<th>Last Edit WikiTreeID</th><th>PageTouched</th></tr>'
            '<tr><td>0</td><td>A</td><td>One,_Brandenburg</td>'
            '<td>Example-123</td><td>20261021</td></tr></table>'
            '<table><tr><th>Level</th><th>LvL</th><th>Category</th>'
            '<th>Last Edit WikiTreeID</th><th>PageTouched</th></tr>'
            '<tr><td>1</td><td>B</td><td>Two,_Brandenburg</td>'
            '<td>Trtnik-2</td><td>20261020</td></tr></table>')
    assert len(parse_categories(html)) == 2
    print('PASS: baseline, allowed edits, excluded edits, duplicates, repeat edits, RSS XML, table parsing')


def main():
    html = retrieve()
    categories = parse_categories(html)
    print('Tables parsed; unique Brandenburg categories:', len(categories))
    if len(categories) < 500:
        raise RuntimeError(f'Incomplete category report: only {len(categories)} rows. Refusing to update state.')
    if STATE_PATH.exists():
        previous = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        events = find_changes(previous, categories)
        print('Qualifying changes:', len(events))
    else:
        events = []
        print('First run: establishing baseline; no notifications.')
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(categories, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(rss_xml(events), encoding='utf-8')
    print('Saved baseline:', STATE_PATH)
    print('Generated RSS:', FEED_PATH)
    print('NOTE: GitHub Actions must commit these files for changes to persist between runs.')


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--self-test', action='store_true')
    args = cli.parse_args()
    if args.self_test:
        self_test()
    else:
        main()

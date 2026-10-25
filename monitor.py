"""Monitor WikiTree+ category edits in five Prussian provinces.

Existing Brandenburg baseline is preserved. New provinces are baselined without
old alerts. Recent RSS items are retained so feed readers can discover them.
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
from xml.etree import ElementTree as ET

PROVINCES = {
    'brandenburg': 'Brandenburg',
    'pommern': 'Pommern',
    'westpreussen': 'Westpreußen',
    'schlesien': 'Schlesien',
    'posen': 'Posen',
}
BASE_URL = 'https://plus.wikitree.com/function/WTCatNavigate/Category.htm'
EXCLUDED = {'sonczalla-1', 'trtnik-2', 'kobus-79'}
STATE_DIR = Path('data')
FEED_PATH = Path('docs/brandenburg.xml')  # Preserve existing MonitoRSS URL.
CATEGORY_URL = 'https://www.wikitree.com/wiki/Category:'
MAX_FEED_ITEMS = 100


def report_url(province):
    category = quote(province + ',_Preußen', safe='')
    return f'{BASE_URL}?Category={category}&Levels=2&Details=Edit'


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
        if not table or not any('Last Edit' in cell for cell in table[0]):
            continue
        for row in table[1:]:
            if len(row) < 4:
                continue
            category, editor, touched = (row[1].strip(), row[2].strip(), row[3].strip())
            if category and 'Last Edit' not in editor:
                categories[category] = {'editor': editor, 'touched': touched}
    return categories


def find_changes(previous, current):
    events = []
    for category, info in sorted(current.items()):
        if previous.get(category) == info:
            continue
        if not info['editor'] or info['editor'].lower() in EXCLUDED:
            continue
        events.append({'category': category, **info})
    return events


def retrieve(url):
    result = subprocess.run(
        ['curl', '-L', '--fail', '--silent', '--show-error', '--max-time', '60',
         '--retry', '2', '-A', 'Mozilla/5.0', url],
        capture_output=True, text=True, check=True)
    return result.stdout


def existing_items():
    if not FEED_PATH.exists():
        return []
    try:
        root = ET.parse(FEED_PATH).getroot()
        return list(root.findall('./channel/item'))
    except ET.ParseError as exc:
        raise RuntimeError('Existing RSS is invalid; refusing to overwrite it') from exc


def write_feed(events):
    rss = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = 'WikiTree Preußen category edits'
    ET.SubElement(channel, 'link').text = report_url('Brandenburg')
    ET.SubElement(channel, 'description').text = 'Category edits in Brandenburg, Pommern, Westpreußen, Schlesien and Posen by non-excluded editors'
    now = format_datetime(datetime.now(timezone.utc), usegmt=True)
    fresh = []
    for province, event in events:
        category, editor, touched = event['category'], event['editor'], event['touched']
        item = ET.Element('item')
        ET.SubElement(item, 'title').text = f'[{province}] {category} - {editor}'
        ET.SubElement(item, 'link').text = CATEGORY_URL + quote(category.replace(' ', '_'), safe='_,()')
        ET.SubElement(item, 'guid', {'isPermaLink': 'false'}).text = f'{province}|{category}|{editor}|{touched}'
        category_link = CATEGORY_URL + quote(category.replace(' ', '_'), safe='_,()')
        ET.SubElement(item, 'description').text = (
            f'Province: {province}; Last editor: {editor}; PageTouched: {touched}\n'
            f'Open WikiTree category: {category_link}'
        )
        ET.SubElement(item, 'pubDate').text = now
        fresh.append(item)

    # Preserve recent real notifications across runs, but discard manual test items.
    seen = set()
    for item in fresh + existing_items():
        guid = item.findtext('guid')
        if not guid or guid.startswith('brandenburg-test-') or guid in seen:
            continue
        seen.add(guid)
        channel.append(item)
        if len(seen) >= MAX_FEED_ITEMS:
            break
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(rss, space='  ')
    xml = ET.tostring(rss, encoding='unicode') + '\n'
    ET.fromstring(xml)
    FEED_PATH.write_text(xml, encoding='utf-8')


def main():
    # Collect and validate ALL provinces before changing any saved files.
    snapshots = {}
    for key, province in PROVINCES.items():
        categories = parse_categories(retrieve(report_url(province)))
        print(f'{province}: {len(categories)} categories parsed')
        if not categories:
            raise RuntimeError(f'{province}: no categories parsed; refusing to update any baselines')
        if key == 'brandenburg' and len(categories) < 500:
            raise RuntimeError('Brandenburg: incomplete report; refusing to update baselines')
        snapshots[key] = categories

    events = []
    for key, province in PROVINCES.items():
        path = STATE_DIR / f'{key}.json'
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            changes = find_changes(previous, snapshots[key])
            print(f'{province}: {len(changes)} qualifying changes')
            events.extend((province, event) for event in changes)
        else:
            print(f'{province}: initial baseline; no old notifications')

    # Prepare RSS before writing baselines; an invalid existing feed fails safely.
    write_feed(events)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for key, categories in snapshots.items():
        (STATE_DIR / f'{key}.json').write_text(
            json.dumps(categories, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(snapshots)} baselines; {len(events)} new events; RSS: {FEED_PATH}')


def self_test():
    original = {'Test,_Brandenburg': {'editor': 'Trtnik-2', 'touched': '20261018'}}
    allowed = {'Test,_Brandenburg': {'editor': 'Example-123', 'touched': '20261021'}}
    assert len(find_changes(original, allowed)) == 1
    assert find_changes(allowed, allowed) == []
    assert find_changes(allowed, {'Test,_Brandenburg': {'editor': 'Kobus-79', 'touched': '20261022'}}) == []
    html = ('<table><tr><th>Level</th><th>Category</th><th>Last Edit WikiTreeID</th><th>PageTouched</th></tr>'
            '<tr><td>1</td><td>Example,_Preußen</td><td>Example-123</td><td>20261021</td></tr></table>')
    assert len(parse_categories(html)) == 1
    for name in PROVINCES.values():
        assert 'Levels=2' in report_url(name)
    print('PASS: parsing, exclusions, changed entries, and province URLs')


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--self-test', action='store_true')
    args = cli.parse_args()
    self_test() if args.self_test else main()

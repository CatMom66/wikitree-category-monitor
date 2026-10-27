"""Monitor 32 Polish/English voivodeship category reports in the existing RSS feed.

First run baselines each report without historical alerts. Exclusions apply per report.
Run after monitor.py, so the shared RSS retains both sets of notifications.
"""
import json
from pathlib import Path
from urllib.parse import quote, unquote

import monitor

# Polish powiat reports and English voivodeship reports, in matching pairs.
PAIRS = [
    ('zachodniopomorskie', 'West_Pomeranian'),
    ('wielkopolskie', 'Greater_Poland'),
    ('pomorskie', 'Pomeranian'),
    ('kujawsko-pomorskie', 'Kuyavian-Pomeranian'),
    ('warmińsko-mazurskie', 'Warmian-Masurian'),
    ('świętokrzyskie', 'Holy_Cross'),
    ('śląskie', 'Silesian'),
    ('podlaskie', 'Podlaskie'),
    ('podkarpackie', 'Subcarpathian'),
    ('opolskie', 'Opole'),
    ('mazowieckie', 'Masovian'),
    ('małopolskie', 'Lesser_Poland'),
    ('dolnośląskie', 'Lower_Silesian'),
    ('lubuskie', 'Lubusz'),
    ('lubelskie', 'Lublin'),
    ('łódzkie', 'Łódź'),
]

BASE_EXCLUDED = {'sonczalla-1', 'trtnik-2', 'kobus-79'}
EXTRA_EXCLUDED = {'jantarek-1', 'dickson-4991'}
STATE_DIR = Path('data/poland')


def reports():
    for i, (polish, english) in enumerate(PAIRS):
        exclusions = BASE_EXCLUDED if i < 4 else BASE_EXCLUDED | EXTRA_EXCLUDED
        yield f'pl_{i:02d}', f'Powiaty,_województwo_{polish},_Polska', exclusions, False
        yield f'en_{i:02d}', f'{english}_Voivodeship,_Poland', exclusions, True


def report_url(category):
    return f'{monitor.BASE_URL}?Category={quote(category, safe="")}&Levels=2&Details=Edit'


def category_name(value):
    if '/wiki/Category:' in value:
        value = unquote(value.split('/wiki/Category:', 1)[1])
    return monitor.normalize_category(value).casefold()


def excluded_branch(name, english, is_lesser_poland):
    # English reports have cemetery/emigrant branches; Polish reports do not.
    if not english:
        return False
    name = category_name(name)
    if 'cemeter' in name or 'emigrant' in name:
        return True
    if is_lesser_poland and 'árva vármegye' in name:
        return True
    return False


def parse_report(html, english=False, is_lesser_poland=False):
    """Parse report rows and exclude descendants of excluded category branches.

    The Level column establishes ancestry; any new child appearing under an
    excluded Level 1 category is automatically excluded at Level 2.
    """
    parser = monitor.Tables()
    parser.feed(html)
    result = {}
    found_table = False
    for table in parser.tables:
        if not table or not any('Last Edit' in cell for cell in table[0]):
            continue
        found_table = True
        excluded_at_level = None
        for row in table[1:]:
            if len(row) < 4:
                continue
            try:
                level = int(row[0].strip())
            except ValueError:
                continue
            category, editor, touched = (v.strip() for v in row[1:4])
            if excluded_at_level is not None and level <= excluded_at_level:
                excluded_at_level = None
            if excluded_at_level is not None:
                continue
            if excluded_branch(category, english, is_lesser_poland):
                excluded_at_level = level
                continue
            if '/wiki/Category:' in category:
                category = unquote(category.split('/wiki/Category:', 1)[1])
            if category and editor:
                result[category] = {'editor': editor, 'touched': touched}
    if not found_table:
        raise RuntimeError('No WikiTree+ Last Edit table found')
    return result


def changes(previous, current, excluded_editors):
    normalized = {monitor.normalize_category(k): v for k, v in previous.items()}
    events = []
    for category, info in sorted(current.items()):
        old = previous.get(category, normalized.get(monitor.normalize_category(category)))
        if old != info and info['editor'].casefold() not in excluded_editors:
            events.append({'category': category, **info})
    return events


def main():
    snapshots = {}
    configurations = list(reports())
    # Validate all 32 reports before changing the RSS or any baseline.
    for key, category, editors, english in configurations:
        html = monitor.retrieve(report_url(category))
        parsed = parse_report(html, english, english and 'Lesser_Poland_' in category)
        if not parsed:
            raise RuntimeError(f'{category}: empty report; no files changed')
        snapshots[key] = parsed
        print(f'{key}: {len(parsed)} monitored categories')

    events = []
    for key, category, editors, english in configurations:
        path = STATE_DIR / f'{key}.json'
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            new_events = changes(previous, snapshots[key], editors)
            events.extend((category.replace('_', ' '), event) for event in new_events)
            print(f'{key}: {len(new_events)} new alerts')
        else:
            print(f'{key}: first-run baseline; no historical alerts')

    # Reuse the existing RSS writer to retain previous Prussian and Polish items.
    monitor.write_feed(events)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for key, snapshot in snapshots.items():
        (STATE_DIR / f'{key}.json').write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(snapshots)} Polish baselines and {len(events)} alerts')


def self_test():
    assert len(list(reports())) == 32
    assert all('Levels=2&Details=Edit' in report_url(cat) for _, cat, _, _ in reports())
    html = '''<table><tr><th>Level</th><th>Category</th><th>Last Edit WikiTreeID</th><th>PageTouched</th></tr>
    <tr><td>0</td><td>Lesser Poland</td><td>Someone-1</td><td>1</td></tr>
    <tr><td>1</td><td>Árva vármegye</td><td>Someone-1</td><td>2</td></tr>
    <tr><td>2</td><td>New subcategory</td><td>Someone-1</td><td>3</td></tr>
    <tr><td>1</td><td>Ordinary category</td><td>Someone-1</td><td>4</td></tr>
    <tr><td>1</td><td>Some Cemeteries</td><td>Someone-1</td><td>5</td></tr>
    <tr><td>2</td><td>New graveyard</td><td>Someone-1</td><td>6</td></tr>
    <tr><td>1</td><td>Emigrants</td><td>Someone-1</td><td>7</td></tr>
    <tr><td>2</td><td>To France</td><td>Someone-1</td><td>8</td></tr></table>'''
    parsed = parse_report(html, True, True)
    assert set(parsed) == {'Lesser Poland', 'Ordinary category'}, parsed
    assert len(changes({}, parsed, BASE_EXCLUDED)) == 2
    assert not changes({}, {'X': {'editor': 'Jantarek-1', 'touched': '1'}}, BASE_EXCLUDED | EXTRA_EXCLUDED)
    print('PASS: 32 reports, report URLs, branch exclusions, editor exclusions')


if __name__ == '__main__':
    import sys
    self_test() if '--self-test' in sys.argv else main()

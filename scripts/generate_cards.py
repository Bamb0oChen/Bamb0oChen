"""Generate repository-hosted SVG cards from GitHub, without dependencies."""
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from update_stats import fetch_repositories, START, END

ROOT = Path(__file__).resolve().parents[1]
USER = 'Bamb0oChen'
COLORS = ['#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#7dcfff', '#f7768e']


class Calendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dates, self.counts = {}, {}
        self.target, self.parts = None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'td' and attrs.get('data-date'):
            self.dates[attrs['id']] = attrs['data-date']
        if tag == 'tool-tip':
            self.target, self.parts = attrs.get('for'), []

    def handle_data(self, data):
        if self.target:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'tool-tip' and self.target:
            match = re.match(r'(No|[\d,]+) contributions? on ', ''.join(self.parts).strip())
            if match:
                self.counts[self.target] = 0 if match[1] == 'No' else int(match[1].replace(',', ''))
            self.target = None


def contributions(now):
    first = now.date() - timedelta(days=30)
    counts = {}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        query = '''query($login:String!,$from:DateTime!,$to:DateTime!) {
          user(login:$login) { contributionsCollection(from:$from,to:$to) {
            contributionCalendar { weeks { contributionDays { date contributionCount } } }
          } }
        }'''
        payload = {'query': query, 'variables': {'login': USER, 'from': f'{first}T00:00:00Z', 'to': now.strftime('%Y-%m-%dT%H:%M:%SZ')}}
        req = Request('https://api.github.com/graphql', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'profile-cards'})
        with urlopen(req, timeout=30) as response:
            data = json.load(response)
        if data.get('errors'):
            raise ValueError('GitHub GraphQL error: ' + json.dumps(data['errors']))
        weeks = data['data']['user']['contributionsCollection']['contributionCalendar']['weeks']
        counts = {d['date']: d['contributionCount'] for w in weeks for d in w['contributionDays']}
    else:
        # Local preview uses GitHub's public calendar; CI uses the official API.
        for year in range(first.year, now.year + 1):
            req = Request(f'https://github.com/users/{USER}/contributions?from={year}-01-01&to={year}-12-31', headers={'User-Agent': 'profile-cards'})
            with urlopen(req, timeout=30) as response:
                parser = Calendar()
                parser.feed(response.read().decode())
            counts.update({date: parser.counts[key] for key, date in parser.dates.items() if key in parser.counts})
    dates = [(first + timedelta(days=i)).isoformat() for i in range(31)]
    if any(date not in counts for date in dates):
        raise ValueError('Incomplete calendar; preserving previous snapshot')
    return [(date, counts[date]) for date in dates]


def text(x, y, value, size=14, color='#a9b1d6', extra=''):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>{escape(str(value))}</text>'


def card(width, height, title, subtitle, body, now):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
            f'<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>'
            '<style>text{font-family:Arial,Helvetica,sans-serif}</style>'
            f'<rect width="{width}" height="{height}" rx="8" fill="#1a1b26"/>'
            + text(24, 34, title, 20, '#c0caf5', 'font-weight="700"')
            + text(24, 57, subtitle, 11) + body
            + text(24, height - 16, f'Updated {now:%Y-%m-%d %H:%M UTC} | GitHub', 10, '#8992b0') + '</svg>')


def activity(days, now):
    ceiling = max(4, math.ceil(max(n for _, n in days) / 4) * 4)
    body = ''
    for i in range(5):
        y = 230 - i * 34
        body += f'<path d="M48 {y} H870" stroke="#30344a"/>' + text(36, y + 4, ceiling * i // 4, 10, extra='text-anchor="end"')
    points = [(48 + i * 27.4, 230 - count / ceiling * 136) for i, (_, count) in enumerate(days)]
    coords = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    body += f'<polygon points="48,230 {coords} 870,230" fill="#7aa2f7" fill-opacity="0.10"/>'
    body += f'<polyline points="{coords}" fill="none" stroke="#7aa2f7" stroke-width="2.5" stroke-linejoin="round"/>'
    for (date, count), (x, y) in zip(days, points):
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#7dcfff"><title>{date}: {count} contributions</title></circle>'
    for i in (0, 5, 10, 15, 20, 25, 30):
        body += text(points[i][0], 253, days[i][0][5:], 10, extra='text-anchor="middle"')
    body += text(870, 34, f'{sum(n for _, n in days)} contributions', 16, '#9ece6a', 'text-anchor="end"')
    return card(900, 294, 'Contribution activity', f'{days[0][0]} to {days[-1][0]} | Last 31 days | Today is partial', body, now)


def overview(repos, days, now):
    metrics = [(len(repos), 'Public repos'), (sum(r['stargazers_count'] for r in repos), 'Stars received'),
               (sum(r['forks_count'] for r in repos), 'Forks received'), (sum(n > 0 for _, n in days), 'Active days / 31')]
    body = ''
    for i, (value, label) in enumerate(metrics):
        x, y = 24 + (i % 2) * 218, 111 + (i // 2) * 85
        body += text(x, y, value, 32, COLORS[i], 'font-weight="700"') + text(x, y + 23, label, 12)
    return card(450, 278, 'GitHub overview', 'Public non-fork repos | Active days: contribution calendar', body, now)


def languages(repos, now):
    counts = Counter(r.get('language') or 'Not detected' for r in repos)
    items = counts.most_common()
    if len(items) > 6:
        items = items[:5] + [('Other', sum(n for _, n in items[5:]))]
    body = ''
    total = sum(counts.values())
    for i, (name, count) in enumerate(items):
        y = 85 + i * 27
        body += text(24, y, name, 12) + text(425, y, f'{count} / {total}', 11, extra='text-anchor="end"')
        body += f'<rect x="160" y="{y - 9}" width="200" height="8" rx="4" fill="#30344a"/>'
        body += f'<rect x="160" y="{y - 9}" width="{200 * count / total:.1f}" height="8" rx="4" fill="{COLORS[i]}"/>'
    if not items:
        body = text(24, 110, 'No public repository language data')
    return card(450, 278, 'Primary languages', 'Repository count | Not code volume or commit share', body, now)


def main():
    now = datetime.now(timezone.utc)
    readme = ROOT / 'README.md'
    original = readme.read_text(encoding='utf-8')
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError('Expected one README marker pair')
    start, end = original.index(START), original.index(END)
    if end < start:
        raise ValueError('Invalid marker order')
    repos = [r for r in fetch_repositories(USER) if not r['fork'] and not r.get('private')]
    days = contributions(now)
    cards = {'activity.svg': activity(days, now), 'overview.svg': overview(repos, days, now), 'languages.svg': languages(repos, now)}
    # Fetch and validate everything before replacing any published files.
    for svg in cards.values():
        ET.fromstring(svg)
    assets = ROOT / 'assets' / 'stats'
    assets.mkdir(parents=True, exist_ok=True)
    for name, svg in cards.items():
        (assets / name).write_text(svg, encoding='utf-8')
    version = now.strftime('%Y%m%d%H%M%S')
    block = f'''{START}
<p align="center">
  <a href="https://github.com/{USER}?tab=overview"><img src="./assets/stats/activity.svg?v={version}" width="100%" alt="GitHub contributions over the last 31 days" /></a>
</p>
<p align="center">
  <img src="./assets/stats/overview.svg?v={version}" width="49%" alt="Public repository statistics and active days" />
  <img src="./assets/stats/languages.svg?v={version}" width="49%" alt="Primary languages by public non-fork repository count" />
</p>
<p align="center"><sub>Generated from GitHub every 6 hours. Timestamps are UTC; today's activity is partial. <a href="https://github.com/{USER}/{USER}/actions/workflows/update-stats.yml">Update status</a></sub></p>
{END}'''
    readme.write_text(original[:start] + block + original[end + len(END):], encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()

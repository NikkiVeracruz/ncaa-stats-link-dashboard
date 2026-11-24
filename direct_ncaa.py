"""Read-only FBS scoreboard parser and one-request feasibility test."""
import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup

BASE = 'https://stats.ncaa.org'
SAMPLE_URL = BASE + '/season_divisions/18904/scoreboards?utf8=%E2%9C%93&season_division_id=&game_date=11%2F21%2F2026&conference_id=0&tournament_id=&commit=Submit'
BOX = re.compile(r'/contests/([1-9]\d*)/box_score')
TEAM = re.compile(r'/teams/([1-9]\d*)')


def path_id(href, pattern):
    u = urlsplit(urljoin(BASE, href or ''))
    if u.scheme != 'https' or u.netloc != 'stats.ncaa.org' or u.query or u.fragment:
        return None
    match = pattern.fullmatch(u.path)
    return match.group(1) if match else None


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse_scoreboard(html, day):
    soup = BeautifulSoup(html, 'html.parser')
    require(soup.h1 and soup.h1.get_text(strip=True) == '2026-27 Football FBS Scoreboard', 'Unexpected scoreboard heading')
    selected = soup.select_one('#season_division_id_select option[selected]')
    date_field = soup.select_one('#game_date')
    require(selected and selected.get('value') == '18904', 'Wrong division')
    require(date_field and date_field.get('value') == day.strftime('%m/%d/%Y'), 'Wrong date')
    tables = [t for t in soup.find_all('table') if t.find('th', string='Game Date')]
    require(len(tables) == 1, 'Missing or ambiguous scoreboard')
    body = tables[0].find('tbody', recursive=False)
    require(body is not None, 'Missing table body')
    rows = body.find_all('tr', recursive=False)
    require(rows and len(rows) % 3 == 0, 'Unexpected scoreboard row grouping')
    games, seen = [], set()
    for i in range(0, len(rows), 3):
        first, second, linkrow = rows[i:i+3]
        cells = first.find_all('td', recursive=False)
        stamp = datetime.strptime(cells[0].get_text(strip=True), '%m/%d/%Y %I:%M %p')
        require(stamp.date() == day, 'Row date mismatch')
        teams = []
        for row in (first, second):
            anchors = [a for a in row.find_all('a', href=True) if path_id(a['href'], TEAM)]
            scores = row.find_all('td', class_='totalcol', recursive=False)
            require(len(anchors) == 1 and len(scores) == 1, 'Ambiguous team or score')
            a = anchors[0]
            score = scores[0].get_text(strip=True)
            require(score == '' or score.isdecimal(), 'Unknown score format')
            teams.append({'id': path_id(a['href'], TEAM), 'name': re.sub(r'\s+\(\d+-\d+(?:-\d+)?\)$', '', a.get_text(strip=True)), 'score': int(score) if score else None})
        require(teams[0]['id'] != teams[1]['id'], 'Duplicate team')
        anchors = linkrow.find_all('a', href=True)
        links = [a for a in anchors if a.get_text(strip=True) == 'Box Score']
        require(len(links) <= 1, 'Ambiguous box score')
        cid = path_id(links[0]['href'], BOX) if links else None
        require(not links or cid, 'Invalid box-score destination')
        if cid:
            require(cid not in seen, 'Duplicate contest ID')
            seen.add(cid)
        games.append({'date': day.isoformat(), 'teams': teams, 'contest_id': cid, 'url': BASE + '/contests/' + cid + '/box_score' if cid else None})
    return games


def verify_saved_box(html, game):
    soup = BeautifulSoup(html, 'html.parser')
    header = soup.select_one('div.table-responsive > table')
    require(header is not None, 'Missing game header')
    teams = list(dict.fromkeys(path_id(a['href'], TEAM) for a in header.find_all('a', href=True) if path_id(a['href'], TEAM)))
    scores = [int(t.get_text(strip=True)) for t in header.find_all('td') if 'font-size:36px' in t.get('style', '') and t.get_text(strip=True).isdecimal()]
    dates = [t.get_text(strip=True) for t in header.find_all('td', class_='grey_text') if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} [AP]M', t.get_text(strip=True))]
    ids = {m.group(1) for a in header.find_all('a', href=True) if (m := re.fullmatch(r'/contests/([1-9]\d*)/(?:team_stats|individual_stats|play_by_play|drives|officials)', a['href']))}
    return bool(game['contest_id'] and ids == {game['contest_id']} and len(teams) == len(scores) == 2 and dict(zip(teams, scores)) == {t['id']: t['score'] for t in game['teams']} and len(dates) == 1 and datetime.strptime(dates[0], '%m/%d/%Y %I:%M %p').date().isoformat() == game['date'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--saved', type=Path)
    p.add_argument('--box', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = {'read_only': True, 'source': 'saved_html' if a.saved else SAMPLE_URL, 'destination_pages_live_verified': False}
    try:
        if a.saved:
            raw = a.saved.read_bytes()
        else:
            # One ordinary request, no cookies, browser impersonation or access-denial retries.
            with urlopen(Request(SAMPLE_URL, headers={'User-Agent': 'ncaa-stats-link-research/0.1', 'Accept': 'text/html'}), timeout=30) as response:
                report['http_status'] = response.status
                require(urlsplit(response.geturl()).netloc == 'stats.ncaa.org', 'Unexpected redirect')
                raw = response.read(2_000_001)
        require(len(raw) <= 2_000_000, 'HTML exceeds size limit')
        games = parse_scoreboard(raw, date(2026, 11, 21))
        report.update(status='parsed', games=len(games), linked=sum(g['url'] is not None for g in games))
        require(report['linked'] > 0, 'No linked games recovered')
        if a.box:
            game = next(g for g in games if g['contest_id'] == '6601304')
            report['saved_box_identity_verified'] = verify_saved_box(a.box.read_bytes(), game)
            require(report['saved_box_identity_verified'], 'Saved box identity mismatch')
    except (HTTPError, URLError, OSError, ValueError, IndexError, StopIteration) as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        if isinstance(exc, HTTPError):
            report['http_status'] = exc.code
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['status'] == 'parsed' else 2


if __name__ == '__main__':
    raise SystemExit(main())

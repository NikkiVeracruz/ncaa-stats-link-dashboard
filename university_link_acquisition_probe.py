"""One read-only official schedule link-discovery feasibility probe.

No production integration, no player data, no stored source HTML, no guessed
report URLs. A robots denial, redirect, failed fetch or ambiguous row stops the
probe. Results are candidates, not verified reports.
"""
import json
import re
import subprocess
from urllib.error import HTTPError
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from urllib.request import Request, build_opener, HTTPRedirectHandler

HOST = "vucommodores.com"
BASE = "https://" + HOST
SOURCE = BASE + "/sports/wbball/schedule"
AGENT = "NCAAReferenceLinkResearch/1.0"
LIMIT = 2_000_000
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def allowed(url):
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == HOST and
                not u.username and not u.password and u.port in (None, 443))
    except ValueError:
        return False


def get(url, content_type):
    if not allowed(url):
        raise ValueError("Unexpected source host")
    with build_opener(NoRedirect()).open(
        Request(url, headers={"User-Agent": AGENT, "Accept": content_type}), timeout=15
    ) as response:
        if response.status != 200 or response.headers.get_content_type() != content_type:
            raise ValueError("Unexpected source status or content type")
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Source exceeds size limit")
    return data.decode("utf-8", errors="strict")


class Node:
    def __init__(self, tag="", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()
    def text(self):
        return " ".join(x.text() if isinstance(x, Node) else x for x in self.children)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(n)
        if tag not in VOID:
            self.stack.append(n)
    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs, self.stack[-1]))
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        if not any(n.tag in ("script", "style", "noscript") for n in self.stack):
            self.stack[-1].children.append(data)


def normalized(text):
    return " ".join(text.lower().split())


def candidates(html, *, opponent="Arizona", day="Nov 23", result="Win 93-62"):
    tree = Tree()
    tree.feed(html)
    if not any(n.tag in ("h1", "h2") and
               "2026-27 women's basketball schedule" in normalized(n.text())
               for n in tree.root.walk()):
        return {}
    # A link must be contained in a single row matching opponent, date and
    # score, not in an unrelated schedule or page-wide ancestor.
    matches = []
    for n in tree.root.walk():
        if n.tag not in ("article", "div", "li", "tr", "section"):
            continue
        text = normalized(n.text())
        if not any(normalized(x.text()) in (opponent.lower(), "vs." + opponent.lower(), "vs. " + opponent.lower(), "at" + opponent.lower(), "at " + opponent.lower()) for x in n.walk()):
            continue
        if not re.search(r"\b" + re.escape(day.lower()) + r"\b", text):
            continue
        if not re.search(r"\b" + re.escape(result.lower()) + r"\b", text):
            continue
        # Reject wrappers containing multiple schedule dates or results.
        if len(re.findall(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\b", text)) != 1:
            continue
        if len(re.findall(r"\b(?:win|loss)\s+\d+\s*-\s*\d+\b", text)) != 1:
            continue
        links = {}
        for a in n.walk():
            if a.tag != "a":
                continue
            label = normalized(a.text()).replace(" opens in a new window", "").strip()
            url = urljoin(SOURCE, a.attrs.get("href", ""))
            if not allowed(url):
                continue
            path = urlsplit(url).path
            if label == "box score" and re.fullmatch(r"/boxscore/\d+", path):
                links.setdefault("box_score", set()).add(url)
            if label == "box score (pdf)" and path.lower().endswith(".pdf"):
                links.setdefault("pdf_candidate", set()).add(url)
        if links:
            matches.append(links)
    merged = {}
    for row in matches:
        for kind, urls in row.items():
            merged.setdefault(kind, set()).update(urls)
    if any(len(urls) != 1 for urls in merged.values()):
        return {}
    return {kind: next(iter(urls)) for kind, urls in merged.items()}



CDN = "https://storage.googleapis.com"
CDN_PREFIX = "/vucommodores-prod/"


def cdn_allowed(url):
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == "storage.googleapis.com" and
                not u.username and not u.password and u.port in (None, 443) and
                u.path.startswith(CDN_PREFIX) and u.path.lower().endswith(".pdf") and
                "%" not in u.path and ".." not in u.path.split("/") and not u.query and not u.fragment)
    except ValueError:
        return False


def download_link(html, parent):
    tree = Tree(); tree.feed(html)
    links = {urljoin(parent, a.attrs.get("href", "")) for a in tree.root.walk()
             if a.tag == "a" and normalized(a.text()) in ("download", "download pdf")}
    links = {u for u in links if cdn_allowed(u)}
    return next(iter(links)) if len(links) == 1 else None


def pdf_identity(text, *, opponent, day, own_score, opponent_score, season):
    # Require exact labeled teams/scores, date, final report marker and sport.
    text = normalized(text)
    required = ("official basketball box score - final", season.lower() + " women's basketball")
    if not all(x in text for x in required):
        return False
    if not re.search(r"\b" + re.escape(day) + r"\b", text):
        return False
    def score(name, value):
        return bool(re.search(r"\b" + re.escape(name.lower()) + r"\s*-\s*" + str(value) + r"\s+record\s*:", text))
    return score("Vanderbilt", own_score) and score(opponent, opponent_score)


def get_pdf(url):
    if not cdn_allowed(url):
        raise ValueError("Unexpected PDF destination")
    # Check the CDN's robots rules as well; RFC 9309 permits access when the
    # robots resource itself is absent (404/410), but not on denial/5xx.
    opener = build_opener(NoRedirect())
    try:
        with opener.open(Request(CDN + "/robots.txt", headers={"User-Agent": AGENT}), timeout=15) as response:
            if response.status != 200 or response.headers.get_content_type() != "text/plain":
                raise ValueError("Unexpected CDN robots response")
            raw = response.read(100_001)
            if len(raw) > 100_000: raise ValueError("CDN robots exceeds limit")
            rules = RobotFileParser(); rules.parse(raw.decode("utf-8").splitlines())
            if not rules.can_fetch(AGENT, url): raise ValueError("CDN robots disallows PDF request")
    except HTTPError as exc:
        if exc.code not in (404, 410): raise
    with opener.open(Request(url, headers={"User-Agent": AGENT, "Accept": "application/pdf"}), timeout=15) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/pdf":
            raise ValueError("PDF destination is not application/pdf")
        data = response.read(8_000_001)
    if len(data) > 8_000_000 or not data.startswith(b"%PDF-"):
        raise ValueError("Invalid or oversized PDF")
    result = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-", "-"], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=True)
    return result.stdout.decode("utf-8", errors="strict")

def main():
    # Explicit one-school, one-sport, one current archive-game control.
    # Stop rather than retry or work around access restrictions.
    robots = RobotFileParser()
    try:
        rules = get(BASE + "/robots.txt", "text/plain")
        if not re.search(r"(?im)^\s*user-agent\s*:", rules):
            raise ValueError("No parseable robots rules")
        robots.parse(rules.splitlines())
        if not robots.can_fetch(AGENT, SOURCE):
            raise ValueError("Robots disallows schedule request")
        links = candidates(get(SOURCE, "text/html"))
        print("UNIVERSITY_LINK_PROBE", json.dumps({
            "control": "wbb:401913059", "date": "2026-11-23",
            "source": SOURCE, "candidates": links, "verified": False
        }), flush=True)
        if set(links) != {"box_score", "pdf_candidate"}:
            return 2
        parent = links["pdf_candidate"]
        if not robots.can_fetch(AGENT, parent):
            raise ValueError("Robots disallows PDF wrapper")
        pdf_url = download_link(get(parent, "text/html"), parent)
        if not pdf_url:
            raise ValueError("No unique official PDF download link")
        text = get_pdf(pdf_url)
        verified = pdf_identity(text, opponent="Arizona", day="11/23/26",
                                own_score=93, opponent_score=62, season="2026-27")
        print("UNIVERSITY_PDF_VERIFICATION", json.dumps({"control":"wbb:401913059",
              "verified":verified, "url":pdf_url}), flush=True)
        return 0 if verified else 4
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        print("UNIVERSITY_LINK_PROBE STOP:", str(exc), flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

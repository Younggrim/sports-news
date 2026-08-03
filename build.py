#!/usr/bin/env python3
"""
Fetches RSS feeds for each team/tab and generates a static HTML site.
Organized by tabs defined in feeds.json. Mirrors the youtube-feed / bible-study pattern.
"""

import base64
import html
import json
import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    import certifi
    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = ssl._create_unverified_context()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SportsNewsBot/1.0)"}


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


# (label, ESPN sport slug, ESPN league slug, ESPN team id/abbreviation)
SCORE_TEAMS = [
    ("Steelers", "football", "nfl", "pit"),
    ("Pirates", "baseball", "mlb", "pit"),
    ("Charlotte FC", "soccer", "usa.1", "21300"),
    ("Penguins", "hockey", "nhl", "pit"),
    ("Kent State", "football", "college-football", "kent"),
    ("Pitt", "football", "college-football", "pitt"),
]


def fetch_json(url: str, retries: int = 3) -> dict | None:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"  Warning: attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt < retries:
                time.sleep(2 * attempt)
    print(f"  ERROR: giving up on {url} after {retries} attempts")
    return None


def fetch_team_scores(sport: str, league: str, team_id: str) -> dict:
    result = {"record": None, "last_game": None, "next_game": None}

    team_data = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}")
    if team_data:
        items = team_data.get("team", {}).get("record", {}).get("items", [])
        if items:
            result["record"] = items[0].get("summary")

    sched_data = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/schedule")
    if sched_data:
        events = sched_data.get("events", [])
        completed = []
        upcoming = []
        for e in events:
            comp = (e.get("competitions") or [{}])[0]
            status = comp.get("status", {}).get("type", {})
            try:
                event_date = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if status.get("completed"):
                completed.append((event_date, e, comp))
            elif status.get("state") == "pre":
                upcoming.append((event_date, e, comp))

        if completed:
            completed.sort(key=lambda x: x[0], reverse=True)
            _, e, comp = completed[0]
            competitors = comp.get("competitors", [])
            parts = []
            for c in competitors:
                name = c.get("team", {}).get("displayName", "?")
                score = c.get("score", {})
                score_val = score.get("displayValue") if isinstance(score, dict) else score
                parts.append(f"{name} {score_val}")
            result["last_game"] = " - ".join(parts) if parts else e.get("name")

        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            event_date, e, comp = upcoming[0]
            result["next_game"] = f"{e.get('shortName', e.get('name'))} - {event_date.strftime('%b %d, %Y')}"

    return result


def fetch_rss(url: str, retries: int = 3) -> list[dict]:
    data = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context) as resp:
                data = resp.read()
            break
        except Exception as e:
            print(f"  Warning: attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt < retries:
                time.sleep(2 * attempt)
    if data is None:
        print(f"  ERROR: giving up on {url} after {retries} attempts")
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"  Warning: could not parse {url}: {e}")
        return []

    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or "Untitled"
        link = item.findtext("link") or ""
        desc = strip_html(item.findtext("description") or "")
        pub_raw = item.findtext("pubDate") or ""
        try:
            pub_date = parsedate_to_datetime(pub_raw)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pub_date = datetime.min.replace(tzinfo=timezone.utc)

        items.append({
            "title": strip_html(title),
            "link": link,
            "desc": desc[:220],
            "pub_date": pub_date,
        })
    return items


def generate_html(tabs_data: list[dict], scores_data: list[dict]) -> str:
    tab_buttons = '    <button class="tab-btn active" data-tab="tab-0">Scores</button>\n'

    score_cards = ""
    for s in scores_data:
        record_line = f'<p class="score-record">Record: {s["record"]}</p>' if s.get("record") else ""
        last_line = f'<p class="score-line">Last: {s["last_game"]}</p>' if s.get("last_game") else ""
        next_line = f'<p class="score-line">Next: {s["next_game"]}</p>' if s.get("next_game") else ""
        if not (record_line or last_line or next_line):
            next_line = '<p class="score-line">No games yet this season</p>'
        score_cards += f"""
      <div class="score-card">
        <h3>{s['label']}</h3>
        {record_line}
        {last_line}
        {next_line}
      </div>"""

    tab_contents = f'    <div class="tab-content score-grid" id="tab-0" style="display: grid;">{score_cards}\n    </div>\n'

    for idx, tab in enumerate(tabs_data):
        i = idx + 1
        tab_buttons += f'    <button class="tab-btn" data-tab="tab-{i}">{tab["label"]}</button>\n'

        all_items = []
        for feed in tab["feeds"]:
            for it in feed["items"]:
                all_items.append({**it, "source": feed["name"]})
        all_items.sort(key=lambda v: v["pub_date"], reverse=True)

        cards = ""
        for it in all_items[:30]:
            pub_display = it["pub_date"].strftime("%b %d, %Y") if it["pub_date"].year > 1 else ""
            title_esc = it["title"].replace('"', "&quot;")
            # Google News redirect feeds put a duplicate of the title in the
            # description instead of a real snippet - skip showing it then.
            desc = it["desc"]
            if desc.lower().startswith(it["title"].lower()[:30]):
                desc = ""
            desc_html = f'<p class="desc">{desc}</p>' if desc else ""
            cards += f"""
      <a class="card" href="{it['link']}" target="_blank" rel="noopener">
        <h3>{title_esc}</h3>
        {desc_html}
        <p class="meta">{it['source']} &bull; {pub_display}</p>
      </a>"""

        tab_contents += f'    <div class="tab-content" id="tab-{i}" style="display: none;">{cards}\n    </div>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sports News</title>
  <link rel="manifest" href="manifest.json">
  <link rel="icon" type="image/png" href="icon-192.png">
  <link rel="apple-touch-icon" href="icon-192.png">
  <meta name="theme-color" content="#0f0f0f">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #f1f1f1; min-height: 100vh; }}
    header {{ background: #1a1a1a; padding: 1rem 2rem; border-bottom: 1px solid #333; }}
    header h1 {{ font-size: 1.5rem; font-weight: 600; }}
    .last-updated {{ color: #aaa; font-size: 0.8rem; margin-top: 0.25rem; }}
    .tabs {{ display: flex; background: #1a1a1a; padding: 0 2rem; border-bottom: 1px solid #333; overflow-x: auto; }}
    .tab-btn {{ background: none; border: none; color: #aaa; padding: 0.75rem 1.5rem; font-size: 1rem; cursor: pointer; border-bottom: 3px solid transparent; white-space: nowrap; }}
    .tab-btn:hover {{ color: #fff; }}
    .tab-btn.active {{ color: #fff; border-bottom-color: #ffb612; }}
    .tab-content {{ padding: 2rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.25rem; }}
    .card {{ background: #1a1a1a; border-radius: 12px; padding: 1.1rem; text-decoration: none; color: inherit; transition: transform 0.15s; display: block; }}
    .card:hover {{ transform: translateY(-2px); background: #222; }}
    .card h3 {{ font-size: 1rem; font-weight: 600; line-height: 1.35; margin-bottom: 0.5rem; }}
    .desc {{ color: #ccc; font-size: 0.85rem; line-height: 1.4; margin-bottom: 0.6rem; }}
    .meta {{ color: #888; font-size: 0.78rem; }}
    .score-card {{ background: #1a1a1a; border-radius: 12px; padding: 1.25rem; }}
    .score-card h3 {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 0.75rem; color: #ffb612; }}
    .score-record {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 0.5rem; }}
    .score-line {{ color: #ccc; font-size: 0.85rem; margin-bottom: 0.3rem; }}
    @media (max-width: 768px) {{
      .tab-content {{ grid-template-columns: 1fr; padding: 1rem; }}
      .tabs {{ padding: 0 1rem; }}
      header {{ padding: 1rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Sports News</h1>
    <p class="last-updated">Last updated: {datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")}</p>
  </header>
  <nav class="tabs">
{tab_buttons}  </nav>
  <main>
{tab_contents}  </main>
  <script>
    document.querySelectorAll('.tab-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).style.display = 'grid';
      }});
    }});
    if ('serviceWorker' in navigator) {{
      window.addEventListener('load', () => navigator.serviceWorker.register('sw.js'));
    }}
  </script>
</body>
</html>"""


PWA_ICON_192_B64 = "iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAYAAABS3GwHAAADzklEQVR4nO3cTXJcNRSA0Q4wb22PFbK93gAVBuCKceHgOHa3rr5zRh6kXI50v6fXv1+u1+vXC0T98ug/AB5JAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKQJgDQBkCYA0gRAmgBIEwBpAiBNAKT99ug/4FS3P3790N+3fv/zQ38ff/tyvV6//vMzDx7y9xLH+wlg2LC/lSjeRgAHDf1rxPA6ARw48P9HEN8IIDT4Ly0PrLsBVIf+NSsaQy4Ag/99KxZCJgCD/2NWJITjAzD4P2cdHsKxARj8j7UODeHI9wIZfmuaPAEM/n2sg06DY04Aw2+tswEYfmuevAUy+HtYg2+JxgZwwvC/HJzJ/6c1NIKRt0CTB+VUt6F7Mi6AqQtdcBu4N6MCmLjANbdhezQmgGkLW3YbtFdjAoBsAJOuKMzas+0DmLKQzNw73wu00fPkz//NhOE5wdYngCGY77Z5yFsHANkAdr9ycMZeegzwwCE46b1AU215AhiE89w2jXvLAOBeBEDadp8H2PWovPf75a3DfTgBSBMAaQIgzesAd+J1gD05AUgTAGkCIM1jgDvxeYA9OQFI2y6Aqd8wxsy93S4AuCePAe7E6wB72vIE2PGo5Mw93TIAuNQD2PWKwVl76THAnXgdYE/bngC7Xzk4Yw+3DgAu9QB2v4Iwe++2+0xw6TOyJ38v0Bow/CNOAPhMYwKYckXhMmqvxgQwbWGr1rA9GhXAxAUuWQP3ZlwAUxf6dGvonox5Fui/nPSsyWRr6PCPD+CJEB5jDR780bdAJ27ENOuQNT8igJM2ZIJ10FofcQv0kluiz7EOGvzjToDTN+rR1qFreuQJ8JzT4OesQwc/E8ATIfyYdfjg5wJ4IoTvW5HBzwbwRAj/Vhv8Sz2A56oxVIf+OQEEQzD43wggEISBf50ADo3B0L+NAA6IwrC/nwCGxGHIP4cASDvyvUDwVgIgTQCkCYA0AZAmANIEQJoASBMAaQIgTQCkCYA0AZAmANIEQJoASBMAaQIgTQCkCYA0AZAmANIEQJoASBMAaQIgTQCkCYA0AZAmANIEQJoASBMAaQIgTQCkCYA0AZAmANIEQJoASBMAaQIgTQCkCYA0AZAmANIEQJoASBMAaQLgUvYX1xznmXC7z3gAAAAASUVORK5CYII="

PWA_ICON_512_B64 = "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2jwCwCMBCPImADcAGAQQY/nzhQDAQIAQy5+vBADfGAywNmect3wGgHf5TwVhHRY/73EDwLsMDFiDs8xHBAAfMjhgbs4w13gEwE08EoB5WPzcwg0ANzFQYA7OKrdyA8BmbgNgPBY/W7kBYDODBsbiTHIPNwA8xG0AnMfi5xECgF0IATiOxc8ePAJgFwYSHMNZYy9uANid2wDYn8XP3gQATyME4HEWP88iAHg6IQDbWfw8mwDgMEIAfs7i5ygCgMMJAfiRxc/RBACnEQJg8XMeAcDphABF3vFzNgHAMIQABRY/oxAADEcIsCKLn9EIAIYmBpiZpc/IBABTEALMxOJnBgKA6YgBRmTpMxsBwNTEAGey9JmZAGAJQoAjWfysQACwHDHAM1j6rEYAsDQxwCMsfVYmAEgRBFxj4VMiAMgSA3xh6VMlAOA/gqDBwod/CQD4gCBYg4UP7xMAsIEoGJtlD7cTAPAAQXAuCx/uJwDgCYTBvix62J8AgAMJg+ssejiOAICBrB4IFjyMQwDAxM4OBgsd5iUAACDo09kvAAA4ngAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAAQJAAAIEgAAECQAACBIAABAkAAAgCABAABBAgAAggQAAPzS8zcz1SDv0zmViAAAAABJRU5ErkJggg=="

PWA_MANIFEST = """{
  "name": "Sports News",
  "short_name": "Sports",
  "description": "Steelers, Pirates, Charlotte FC, and Penguins news in one feed.",
  "start_url": "/index.html",
  "display": "standalone",
  "background_color": "#0f0f0f",
  "theme_color": "#0f0f0f",
  "orientation": "any",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
"""

PWA_SERVICE_WORKER = """const CACHE_NAME = 'sports-news-v1';

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(['/index.html']))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""


def main():
    script_dir = Path(__file__).parent
    config = json.loads((script_dir / "feeds.json").read_text())
    output_dir = script_dir / "docs"

    tabs_data = []
    for tab in config["tabs"]:
        print(f"\nProcessing tab: {tab['label']}")
        tab_info = {"label": tab["label"], "feeds": []}
        for feed in tab["feeds"]:
            print(f"  Fetching: {feed['name']} ({feed['url']})")
            items = fetch_rss(feed["url"])
            print(f"  Found {len(items)} items")
            tab_info["feeds"].append({"name": feed["name"], "items": items})
        tabs_data.append(tab_info)

    print("\nFetching scores/standings...")
    scores_data = []
    for label, sport, league, team_id in SCORE_TEAMS:
        print(f"  {label} ({sport}/{league}/{team_id})")
        s = fetch_team_scores(sport, league, team_id)
        s["label"] = label
        scores_data.append(s)

    html_out = generate_html(tabs_data, scores_data)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html_out)
    (output_dir / "CNAME").write_text("sports.news.macdwellings.com\n")
    (output_dir / "manifest.json").write_text(PWA_MANIFEST)
    (output_dir / "sw.js").write_text(PWA_SERVICE_WORKER)
    (output_dir / "icon-192.png").write_bytes(base64.b64decode(PWA_ICON_192_B64))
    (output_dir / "icon-512.png").write_bytes(base64.b64decode(PWA_ICON_512_B64))
    print(f"\nOutput written to: {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()

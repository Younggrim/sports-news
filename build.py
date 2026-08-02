#!/usr/bin/env python3
"""
Fetches RSS feeds for each team/tab and generates a static HTML site.
Organized by tabs defined in feeds.json. Mirrors the youtube-feed / bible-study pattern.
"""

import html
import json
import re
import ssl
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


def fetch_rss(url: str) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  Warning: could not fetch {url}: {e}")
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


def generate_html(tabs_data: list[dict]) -> str:
    tab_buttons = ""
    tab_contents = ""

    for i, tab in enumerate(tabs_data):
        active = " active" if i == 0 else ""
        tab_buttons += f'    <button class="tab-btn{active}" data-tab="tab-{i}">{tab["label"]}</button>\n'

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

        display = "grid" if i == 0 else "none"
        tab_contents += f'    <div class="tab-content" id="tab-{i}" style="display: {display};">{cards}\n    </div>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sports News</title>
  <link rel="manifest" href="manifest.json">
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


PWA_MANIFEST = """{
  "name": "Sports News",
  "short_name": "Sports",
  "description": "Steelers, Pirates, Charlotte FC, and Penguins news in one feed.",
  "start_url": "/index.html",
  "display": "standalone",
  "background_color": "#0f0f0f",
  "theme_color": "#0f0f0f",
  "orientation": "any",
  "icons": []
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

    html_out = generate_html(tabs_data)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html_out)
    (output_dir / "CNAME").write_text("sports.news.macdwellings.com\n")
    (output_dir / "manifest.json").write_text(PWA_MANIFEST)
    (output_dir / "sw.js").write_text(PWA_SERVICE_WORKER)
    print(f"\nOutput written to: {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Paprika Recipe Website Builder

Parses the latest .paprikarecipes export file and generates a static website
suitable for deployment on Netlify.

Usage:
    python build.py [data_dir] [output_dir]
    Defaults: data_dir=./data, output_dir=./dist
"""

import os
import sys
import json
import gzip
import zipfile
import re
import shutil
import glob
import base64
import struct
import zlib
from pathlib import Path
from collections import defaultdict
from html import escape


# ─── Utilities ────────────────────────────────────────────────────────────────

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    return text or 'recipe'


def star_html(rating):
    if not rating:
        return ''
    filled = '★' * rating
    empty = '☆' * (5 - rating)
    return f'<span class="stars" aria-label="{rating} out of 5 stars">{filled}{empty}</span>'


def format_time(t):
    return t.strip() if t and t.strip() else ''


def parse_ingredients(text):
    """Split ingredients into sections and items."""
    if not text:
        return []
    lines = text.split('\n')
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Section header: all caps, or ends with colon, or no quantities
        if re.match(r'^[A-Z][A-Z\s]+$', line) or line.endswith(':'):
            result.append({'type': 'header', 'text': line.rstrip(':')})
        else:
            result.append({'type': 'item', 'text': line})
    return result


def parse_directions(text):
    """Split directions into steps."""
    if not text:
        return []
    # Split on double newlines first
    blocks = re.split(r'\n{2,}', text.strip())
    steps = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # If block starts with a number, it might be a single step
        # Or it might be multiple numbered lines
        lines = block.split('\n')
        for line in lines:
            line = line.strip()
            if line:
                # Remove leading number like "1." or "1)" or "Step 1:"
                cleaned = re.sub(r'^(Step\s+)?\d+[\.\)]\s*', '', line, flags=re.IGNORECASE)
                steps.append(cleaned)
    return steps


# ─── Parsing ──────────────────────────────────────────────────────────────────

def find_latest_paprika_file(data_dir):
    files = glob.glob(str(Path(data_dir) / '*.paprikarecipes'))
    if not files:
        print(f"Error: No .paprikarecipes files found in '{data_dir}'")
        sys.exit(1)
    latest = max(files, key=os.path.getmtime)
    print(f"  Source: {os.path.basename(latest)}")
    return latest


def parse_paprika_export(filepath):
    recipes = []
    with zipfile.ZipFile(filepath, 'r') as zf:
        for name in zf.namelist():
            if name.endswith('.paprikarecipe'):
                with zf.open(name) as f:
                    try:
                        recipe = json.loads(gzip.decompress(f.read()))
                        recipes.append(recipe)
                    except Exception as e:
                        print(f"  Warning: skipping {name}: {e}")
    recipes.sort(key=lambda r: r.get('name', '').lower())
    print(f"  Loaded {len(recipes)} recipes")
    return recipes


def normalize_categories(categories):
    return sorted(set(c.strip() for c in (categories or []) if c and c.strip()))


def process_recipes(raw_recipes):
    slugs_seen = {}
    processed = []

    for r in raw_recipes:
        name = (r.get('name') or 'Untitled').strip()
        uid = r.get('uid', '')

        base_slug = slugify(name)
        slug = base_slug
        if slug in slugs_seen:
            slugs_seen[slug] += 1
            slug = f"{base_slug}-{slugs_seen[slug]}"
        else:
            slugs_seen[slug] = 0

        cats = normalize_categories(r.get('categories', []))
        has_photo = bool(r.get('photo_data', ''))

        ingredients_raw = (r.get('ingredients') or '').strip()
        directions_raw = (r.get('directions') or '').strip()
        description = (r.get('description') or '').strip()
        notes = (r.get('notes') or '').strip()

        # Build searchable blob
        searchable = ' '.join(filter(None, [
            name.lower(),
            ' '.join(c.lower() for c in cats),
            ingredients_raw.lower(),
            description.lower(),
        ]))

        processed.append({
            'uid': uid,
            'slug': slug,
            'name': name,
            'categories': cats,
            'ingredients': ingredients_raw,
            'ingredients_parsed': parse_ingredients(ingredients_raw),
            'directions': directions_raw,
            'directions_parsed': parse_directions(directions_raw),
            'description': description,
            'notes': notes,
            'nutritional_info': (r.get('nutritional_info') or '').strip(),
            'prep_time': format_time(r.get('prep_time', '')),
            'cook_time': format_time(r.get('cook_time', '')),
            'total_time': format_time(r.get('total_time', '')),
            'servings': (r.get('servings') or '').strip(),
            'difficulty': (r.get('difficulty') or '').strip(),
            'rating': r.get('rating') or 0,
            'source': (r.get('source') or '').strip(),
            'source_url': (r.get('source_url') or '').strip(),
            'has_photo': has_photo,
            'searchable': searchable,
        })

    return processed


def extract_images(raw_recipes, images_dir):
    os.makedirs(images_dir, exist_ok=True)
    count = 0
    for r in raw_recipes:
        uid = r.get('uid', '')
        photo_data = r.get('photo_data', '')
        if uid and photo_data:
            try:
                img_bytes = base64.b64decode(photo_data)
                with open(Path(images_dir) / f"{uid}.jpg", 'wb') as f:
                    f.write(img_bytes)
                count += 1
            except Exception as e:
                print(f"  Warning: image for '{r.get('name', uid)}': {e}")
    print(f"  Extracted {count} images")


# ─── CSS ──────────────────────────────────────────────────────────────────────

COMMON_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #faf9f6;
  --surface: #ffffff;
  --border: #e4e0d8;
  --text: #1c1c1a;
  --muted: #6b6660;
  --green: #1e5631;
  --green-mid: #2d7a44;
  --green-light: #eaf3ec;
  --amber: #c87800;
  --star: #f0a500;
  --radius: 12px;
  --shadow: 0 2px 10px rgba(0,0,0,.09);
  --shadow-hover: 0 6px 24px rgba(0,0,0,.14);
  font-size: 16px;
}

body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  min-height: 100vh;
}

img { max-width: 100%; height: auto; display: block; }
a { color: var(--green); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Header ── */
.site-header {
  background: var(--green);
  color: #fff;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 12px rgba(0,0,0,.25);
}
.header-inner {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0 1.25rem;
  height: 60px;
  max-width: 1400px;
  margin: 0 auto;
}
.site-title {
  font-size: 1.35rem;
  font-weight: 800;
  white-space: nowrap;
  letter-spacing: -0.3px;
}
.site-title a { color: #fff; }
.site-title a:hover { text-decoration: none; opacity: .85; }
.header-count {
  font-size: .8rem;
  opacity: .65;
  white-space: nowrap;
}
.search-wrap {
  flex: 1;
  max-width: 440px;
  position: relative;
}
.search-input {
  width: 100%;
  padding: .5rem 1rem .5rem 2.4rem;
  border-radius: 24px;
  border: none;
  font-size: .9rem;
  background: rgba(255,255,255,.18);
  color: #fff;
  outline: none;
  transition: background .2s;
}
.search-input::placeholder { color: rgba(255,255,255,.55); }
.search-input:focus { background: rgba(255,255,255,.28); }
.search-icon {
  position: absolute;
  left: .75rem;
  top: 50%;
  transform: translateY(-50%);
  opacity: .7;
  pointer-events: none;
}
.clear-btn {
  position: absolute;
  right: .6rem;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(255,255,255,.3);
  border: none;
  color: #fff;
  cursor: pointer;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  font-size: 12px;
  display: none;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.clear-btn.visible { display: flex; }

/* ── Category filter bar ── */
.filter-bar {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: .65rem 1.25rem;
  display: flex;
  gap: .45rem;
  overflow-x: auto;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.filter-bar::-webkit-scrollbar { display: none; }
.filter-btn {
  padding: .35rem .85rem;
  border-radius: 20px;
  border: 1.5px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
  font-size: .82rem;
  font-weight: 600;
  transition: all .15s;
  flex-shrink: 0;
}
.filter-btn:hover { border-color: var(--green-mid); color: var(--green-mid); }
.filter-btn.active {
  background: var(--green);
  border-color: var(--green);
  color: #fff;
}

/* ── Results bar ── */
.results-bar {
  padding: .75rem 1.5rem .25rem;
  font-size: .82rem;
  color: var(--muted);
  max-width: 1400px;
  margin: 0 auto;
}

/* ── Recipe Grid ── */
.recipe-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 1.25rem;
  padding: .75rem 1.25rem 3rem;
  max-width: 1400px;
  margin: 0 auto;
}

/* ── Recipe Card ── */
.recipe-card {
  background: var(--surface);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  transition: transform .2s, box-shadow .2s;
  display: flex;
  flex-direction: column;
  color: var(--text);
}
.recipe-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-hover);
  text-decoration: none;
}
.card-body {
  padding: .9rem 1rem;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: .4rem;
}
.card-cats {
  display: flex;
  flex-wrap: wrap;
  gap: .3rem;
}
.cat-tag {
  background: var(--green-light);
  color: var(--green);
  padding: .15rem .55rem;
  border-radius: 20px;
  font-size: .72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .3px;
}
.card-name {
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.35;
}
.card-footer {
  display: flex;
  align-items: center;
  gap: .75rem;
  font-size: .78rem;
  color: var(--muted);
  flex-wrap: wrap;
}
.stars { color: var(--star); }

/* ── No results ── */
.no-results {
  grid-column: 1 / -1;
  text-align: center;
  padding: 5rem 1rem;
  color: var(--muted);
}
.no-results .emoji { font-size: 4rem; margin-bottom: 1rem; }
.no-results h2 { font-size: 1.4rem; margin-bottom: .5rem; color: var(--text); }

/* ── Recipe Detail Page ── */
.back-link {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  font-size: .9rem;
  font-weight: 600;
  color: var(--green);
  padding: 1rem 1.25rem .5rem;
  max-width: 1200px;
  margin: 0 auto;
  display: block;
}
.recipe-hero {
  max-width: 1200px;
  margin: 0 auto;
  padding: .5rem 1.25rem 1rem;
}
.recipe-meta-block h1 {
  font-size: 1.9rem;
  font-weight: 800;
  line-height: 1.25;
  margin-bottom: .6rem;
  letter-spacing: -.5px;
}
.recipe-cats {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin-bottom: .9rem;
}
.recipe-cats .cat-tag { font-size: .8rem; padding: .25rem .7rem; }
.recipe-details-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .4rem .75rem;
  font-size: .88rem;
  border-top: 1px solid var(--border);
  padding-top: .9rem;
  margin-top: .5rem;
}
.detail-item { display: flex; flex-direction: column; }
.detail-label { font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); }
.detail-value { font-weight: 600; color: var(--text); }
.recipe-description {
  margin-top: .9rem;
  font-size: .93rem;
  color: var(--muted);
  font-style: italic;
  border-left: 3px solid var(--green-light);
  padding-left: .75rem;
}
.rating-stars { font-size: 1.3rem; color: var(--star); margin-bottom: .3rem; }

/* ── Recipe Content ── */
.recipe-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 3rem;
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 2rem;
  align-items: start;
}
.ingredients-section {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 1.25rem;
  box-shadow: var(--shadow);
  position: sticky;
  top: 76px;
}
.ingredients-section h2,
.directions-section h2,
.notes-section h2 {
  font-size: 1.05rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .8px;
  color: var(--green);
  margin-bottom: 1rem;
  padding-bottom: .5rem;
  border-bottom: 2px solid var(--green-light);
}
.ingredients-section h2::before { content: '🧺 '; }
.directions-section h2::before { content: '📋 '; }
.notes-section h2::before { content: '📝 '; }

.ingredient-header {
  font-size: .8rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .6px;
  color: var(--muted);
  margin: .9rem 0 .4rem;
}
.ingredient-header:first-child { margin-top: 0; }
.ingredient-item {
  display: flex;
  gap: .5rem;
  padding: .3rem 0;
  font-size: .9rem;
  border-bottom: 1px solid var(--border);
  line-height: 1.4;
}
.ingredient-item:last-child { border-bottom: none; }
.ingredient-bullet {
  color: var(--green-mid);
  flex-shrink: 0;
  margin-top: .1rem;
}

.directions-section { }
.step {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.25rem;
  align-items: flex-start;
}
.step-num {
  background: var(--green);
  color: #fff;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: .8rem;
  font-weight: 800;
  flex-shrink: 0;
  margin-top: .15rem;
}
.step-text { font-size: .93rem; line-height: 1.65; }

.notes-section {
  background: #fffbf0;
  border-left: 4px solid var(--amber);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 1.1rem 1.25rem;
  margin-top: 1.5rem;
  grid-column: 1 / -1;
  font-size: .92rem;
  line-height: 1.65;
  color: var(--text);
}
.source-link {
  grid-column: 1 / -1;
  font-size: .82rem;
  color: var(--muted);
  padding-top: .5rem;
  border-top: 1px solid var(--border);
  margin-top: .5rem;
}
.source-link a { color: var(--green-mid); }

/* ── Footer ── */
.site-footer {
  background: var(--green);
  color: rgba(255,255,255,.7);
  text-align: center;
  padding: 1.5rem;
  font-size: .82rem;
  margin-top: auto;
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .recipe-content {
    grid-template-columns: 1fr;
  }
  .ingredients-section {
    position: static;
  }
}

@media (max-width: 640px) {
  .header-inner { gap: .6rem; padding: 0 .9rem; }
  .site-title { font-size: 1.1rem; }
  .header-count { display: none; }
  .recipe-hero { padding: .5rem .9rem .75rem; }
  .recipe-meta-block h1 { font-size: 1.5rem; }
  .recipe-content { padding: 1rem .9rem 2rem; gap: 1.25rem; }
  .recipe-grid { padding: .5rem .9rem 2rem; gap: 1rem; }
  .filter-bar { padding: .55rem .9rem; }
  .back-link { padding: .75rem .9rem .25rem; }
}

@media (max-width: 480px) {
  .recipe-grid { grid-template-columns: 1fr 1fr; }
  .card-body { padding: .7rem .75rem; }
  .card-name { font-size: .9rem; }
}

@media (max-width: 360px) {
  .recipe-grid { grid-template-columns: 1fr; }
}
"""


# ─── JavaScript (index page) ──────────────────────────────────────────────────

def make_png(width, height, r, g, b):
    """Generate a minimal solid-colour PNG without external libs."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    sig   = b'\x89PNG\r\n\x1a\n'
    ihdr  = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    row   = bytes([0]) + bytes([r, g, b] * width)
    idat  = chunk(b'IDAT', zlib.compress(row * height, 9))
    iend  = chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#1e5631"/>
  <text x="256" y="360" font-size="300" text-anchor="middle" font-family="system-ui,sans-serif">🌿</text>
</svg>"""

SERVICE_WORKER_JS = """
const CACHE = 'famalita-v1';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.add('/')));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
"""

INDEX_JS = """
(function() {
  const grid = document.getElementById('recipe-grid');
  const countEl = document.getElementById('results-count');
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('clear-btn');
  const filterBtns = document.querySelectorAll('.filter-btn');

  let activeCategory = 'all';
  let searchQuery = '';

  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function cardHtml(r) {
    const cats = r.categories.length
      ? `<div class="card-cats">${r.categories.map(c=>`<span class="cat-tag">${esc(c)}</span>`).join('')}</div>`
      : '';

    const stars = r.rating ? `<span class="stars">${'★'.repeat(r.rating)}${'☆'.repeat(5-r.rating)}</span>` : '';
    const time = r.total_time || (r.prep_time && r.cook_time
      ? r.prep_time + ' + ' + r.cook_time
      : r.prep_time || r.cook_time) || '';
    const servings = r.servings ? `<span>Serves ${esc(r.servings)}</span>` : '';

    const footer = (stars || time || servings)
      ? `<div class="card-footer">${stars}${time ? `<span>⏱ ${esc(time)}</span>` : ''}${servings}</div>`
      : '';

    return `<a href="recipe/${esc(r.slug)}.html" class="recipe-card">
      <div class="card-body">
        ${cats}
        <div class="card-name">${esc(r.name)}</div>
        ${footer}
      </div>
    </a>`;
  }

  function tokenize(s) {
    return s.toLowerCase().replace(/[^a-z0-9\u00C0-\u024F\s]/g,'').split(/\s+/).filter(Boolean);
  }

  function matches(r, query) {
    if (!query) return true;
    const tokens = tokenize(query);
    const hay = r.searchable;
    return tokens.every(tok => hay.includes(tok));
  }

  function render() {
    const filtered = RECIPES.filter(r => {
      const catOk = activeCategory === 'all' || r.categories.includes(activeCategory);
      return catOk && matches(r, searchQuery);
    });

    countEl.textContent = filtered.length === RECIPES.length
      ? `${RECIPES.length} recipes`
      : `${filtered.length} of ${RECIPES.length} recipes`;

    if (filtered.length === 0) {
      grid.innerHTML = `<div class="no-results">
        <div class="emoji">🔍</div>
        <h2>No recipes found</h2>
        <p>Try a different search term or category.</p>
      </div>`;
    } else {
      grid.innerHTML = filtered.map(cardHtml).join('');
    }
  }

  searchInput.addEventListener('input', function() {
    searchQuery = this.value.trim();
    clearBtn.classList.toggle('visible', searchQuery.length > 0);
    render();
  });

  clearBtn.addEventListener('click', function() {
    searchInput.value = '';
    searchQuery = '';
    clearBtn.classList.remove('visible');
    searchInput.focus();
    render();
  });

  filterBtns.forEach(btn => {
    btn.addEventListener('click', function() {
      filterBtns.forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      activeCategory = this.dataset.cat;
      render();
    });
  });

  // Initial render
  render();

  // Handle keyboard shortcut: "/" to focus search
  document.addEventListener('keydown', function(e) {
    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
    }
    if (e.key === 'Escape') {
      searchInput.blur();
    }
  });
})();
"""


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def html_page(title, body, extra_head='', root=''):
    """Wrap body in a full HTML document."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1e5631">
  <link rel="manifest" href="{root}manifest.json">
  <link rel="apple-touch-icon" href="{root}icons/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Famalita">
  <title>{escape(title)}</title>
  <style>{COMMON_CSS}</style>
  {extra_head}
</head>
<body>
{body}
<script>if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');</script>
</body>
</html>"""


def header_html(title, count, show_search=True, root=''):
    search_part = ''
    if show_search:
        search_part = """
    <div class="search-wrap">
      <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
           stroke="white" stroke-width="2.5" stroke-linecap="round">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input id="search-input" class="search-input" type="search"
             placeholder="Search recipes… (press /)" autocomplete="off" spellcheck="false">
      <button id="clear-btn" class="clear-btn" aria-label="Clear search">✕</button>
    </div>"""

    return f"""<header class="site-header">
  <div class="header-inner">
    <div class="site-title"><a href="{root}index.html">🌿 {escape(title)}</a></div>
    <span class="header-count">{count} recipes</span>
    {search_part}
  </div>
</header>"""


def footer_html():
    return """<footer class="site-footer">
  Made with Paprika &amp; Python · Generated by build.py
</footer>"""


# ─── Index page ───────────────────────────────────────────────────────────────

def build_index(recipes_data, all_categories, site_title, dist_dir):
    # Minimal recipe data for JS (strip bulky parsed fields)
    js_recipes = [{
        'uid': r['uid'],
        'slug': r['slug'],
        'name': r['name'],
        'categories': r['categories'],
        'has_photo': r['has_photo'],
        'prep_time': r['prep_time'],
        'cook_time': r['cook_time'],
        'total_time': r['total_time'],
        'servings': r['servings'],
        'rating': r['rating'],
        'searchable': r['searchable'],
    } for r in recipes_data]

    recipes_json = json.dumps(js_recipes, ensure_ascii=False, separators=(',', ':'))

    filter_buttons = ['<button class="filter-btn active" data-cat="all">All</button>']
    for cat in all_categories:
        count = sum(1 for r in recipes_data if cat in r['categories'])
        filter_buttons.append(
            f'<button class="filter-btn" data-cat="{escape(cat)}">{escape(cat)} <span style="opacity:.6">({count})</span></button>'
        )

    body = f"""{header_html(site_title, len(recipes_data), show_search=True)}
<nav class="filter-bar">
  {''.join(filter_buttons)}
</nav>
<div class="results-bar"><span id="results-count"></span></div>
<main>
  <div id="recipe-grid" class="recipe-grid"></div>
</main>
{footer_html()}
<script>
const RECIPES = {recipes_json};
{INDEX_JS}
</script>"""

    path = Path(dist_dir) / 'index.html'
    path.write_text(html_page(site_title, body), encoding='utf-8')
    print(f"  index.html")


# ─── Recipe detail pages ──────────────────────────────────────────────────────

def build_recipe_page(recipe, site_title, dist_dir):
    r = recipe
    recipe_dir = Path(dist_dir) / 'recipe'
    recipe_dir.mkdir(exist_ok=True)

    # Category tags
    cats_html = ''.join(f'<span class="cat-tag">{escape(c)}</span>' for c in r['categories'])

    # Metadata grid
    details = []
    if r['prep_time']:
        details.append(('Prep', r['prep_time']))
    if r['cook_time']:
        details.append(('Cook', r['cook_time']))
    if r['total_time']:
        details.append(('Total', r['total_time']))
    if r['servings']:
        details.append(('Serves', r['servings']))
    if r['difficulty']:
        details.append(('Difficulty', r['difficulty']))

    details_html = ''.join(
        f'<div class="detail-item"><span class="detail-label">{escape(label)}</span>'
        f'<span class="detail-value">{escape(val)}</span></div>'
        for label, val in details
    )

    rating_html = f'<div class="rating-stars">{star_html(r["rating"])}</div>' if r['rating'] else ''
    description_html = f'<p class="recipe-description">{escape(r["description"])}</p>' if r['description'] else ''

    # Ingredients
    ing_items = []
    for item in r['ingredients_parsed']:
        if item['type'] == 'header':
            ing_items.append(f'<div class="ingredient-header">{escape(item["text"])}</div>')
        else:
            ing_items.append(
                f'<div class="ingredient-item">'
                f'<span class="ingredient-bullet">▸</span>'
                f'<span>{escape(item["text"])}</span>'
                f'</div>'
            )
    ingredients_html = ''.join(ing_items) if ing_items else '<p style="color:var(--muted)">No ingredients listed.</p>'

    # Directions
    steps_html = ''
    for i, step in enumerate(r['directions_parsed'], 1):
        steps_html += (
            f'<div class="step">'
            f'<div class="step-num">{i}</div>'
            f'<div class="step-text">{escape(step)}</div>'
            f'</div>'
        )
    if not steps_html:
        steps_html = '<p style="color:var(--muted)">No directions listed.</p>'

    # Notes
    notes_html = ''
    if r['notes']:
        notes_html = f'<div class="notes-section"><h2>Notes</h2><div>{escape(r["notes"]).replace(chr(10), "<br>")}</div></div>'

    # Source
    source_html = ''
    if r['source_url']:
        src_label = escape(r['source'] or r['source_url'])
        source_html = f'<div class="source-link">Source: <a href="{escape(r["source_url"])}" target="_blank" rel="noopener">{src_label}</a></div>'
    elif r['source']:
        source_html = f'<div class="source-link">Source: {escape(r["source"])}</div>'

    body = f"""{header_html(site_title, '', show_search=False, root='../')}
<a class="back-link" href="../index.html">← All Recipes</a>

<div class="recipe-hero">
  <div class="recipe-meta-block">
    {rating_html}
    <h1>{escape(r['name'])}</h1>
    {f'<div class="recipe-cats">{cats_html}</div>' if cats_html else ''}
    {f'<div class="recipe-details-grid">{details_html}</div>' if details_html else ''}
    {description_html}
  </div>
</div>

<div class="recipe-content">
  <aside class="ingredients-section">
    <h2>Ingredients</h2>
    {ingredients_html}
  </aside>
  <div>
    <div class="directions-section">
      <h2>Directions</h2>
      {steps_html}
    </div>
    {notes_html}
    {source_html}
  </div>
</div>
{footer_html()}"""

    page_title = f"{r['name']} — {site_title}"
    path = recipe_dir / f"{r['slug']}.html"
    path.write_text(html_page(page_title, body), encoding='utf-8')


# ─── Main build ───────────────────────────────────────────────────────────────

def build(data_dir='data', out_dir='dist', site_title='Famalita Recipes'):
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)

    print("\n── Paprika Recipe Website Builder ─────────────────────")

    # Clean output
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    (out_dir / 'recipe').mkdir()

    # Parse
    print("\n[1/4] Parsing export…")
    filepath = find_latest_paprika_file(data_dir)
    raw_recipes = parse_paprika_export(filepath)

    print("\n[2/4] Processing recipes…")
    recipes_data = process_recipes(raw_recipes)
    all_categories = sorted(set(c for r in recipes_data for c in r['categories']))
    print(f"  {len(all_categories)} categories: {', '.join(all_categories)}")

    print("\n[3/3] Generating pages…")
    build_index(recipes_data, all_categories, site_title, out_dir)
    for r in recipes_data:
        build_recipe_page(r, site_title, out_dir)
    print(f"  {len(recipes_data)} recipe pages")

    # PWA assets
    icons_dir = out_dir / 'icons'
    icons_dir.mkdir(exist_ok=True)
    (icons_dir / 'icon.svg').write_text(ICON_SVG, encoding='utf-8')
    # 180x180 PNG for iOS apple-touch-icon (dark green #1e5631 = 30,86,49)
    (icons_dir / 'apple-touch-icon.png').write_bytes(make_png(180, 180, 30, 86, 49))
    # 512x512 PNG for Android/desktop
    (icons_dir / 'icon-512.png').write_bytes(make_png(512, 512, 30, 86, 49))
    manifest = {
        'name': site_title,
        'short_name': 'Famalita',
        'description': 'Our family recipe collection',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#faf9f6',
        'theme_color': '#1e5631',
        'icons': [
            {'src': '/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/icons/apple-touch-icon.png', 'sizes': '180x180', 'type': 'image/png'},
        ],
    }
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (out_dir / 'sw.js').write_text(SERVICE_WORKER_JS, encoding='utf-8')
    print("  PWA assets (manifest, service worker, icon)")

    print(f"\n✓ Built {len(recipes_data)} recipes → {out_dir}/")
    print(f"  Open {out_dir}/index.html in a browser to preview\n")


if __name__ == '__main__':
    args = sys.argv[1:]
    data_dir = args[0] if len(args) > 0 else 'data'
    out_dir = args[1] if len(args) > 1 else 'dist'
    site_title = args[2] if len(args) > 2 else 'Famalita Recipes'
    build(data_dir, out_dir, site_title)

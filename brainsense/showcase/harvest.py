"""Harvest a live page's real assets with Playwright so a redesign can EVOLVE the page instead of
replacing it: viewport (1× and 2×) and full-page captures, every <img>/<picture>/background-image,
the logo, inline SVGs, 2× element screenshots of maps/canvases/iframes/charts, and a DOM outline
(headings, nav links, sections). Everything lands in <out>/assets/ with a manifest."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 BrainSense/0.1"
JS_COLLECT = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const small = r.width >= 14 && r.height >= 14 && !!el.closest('a[href="/"], header, nav, [class*=logo], [id*=logo], a[href^="https://' + location.host + '"]'); return (r.width > 24 && r.height > 24 || small) && r.bottom > 0 && r.top < document.documentElement.scrollHeight; };
  const imgs = [...document.querySelectorAll('img')].filter(vis).map((el, i) => {
    const r = el.getBoundingClientRect();
    return { kind: 'img', idx: i, src: el.currentSrc || el.src, alt: el.alt || '', w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + scrollY), left: Math.round(r.left + scrollX),
             cls: (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '') + ' ' + (el.id || ''), inHeader: !!el.closest('header, nav, [class*=logo], [id*=logo]') };
  });
  const bgs = [];
  for (const el of document.querySelectorAll('*')) {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg.startsWith('url(') && vis(el)) { const r = el.getBoundingClientRect(); const m = bg.match(/url\(["']?(.*?)["']?\)/); if (m && !m[1].startsWith('data:image/svg')) bgs.push({ kind: 'bg', src: m[1], w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + scrollY), left: Math.round(r.left + scrollX), cls: (el.className || '') + ' ' + (el.id || '') }); }
    if (bgs.length > 40) break;
  }
  const svgs = [...document.querySelectorAll('svg')].filter(vis).slice(0, 30).map((el, i) => { const r = el.getBoundingClientRect(); const html = el.outerHTML; return { kind: 'svg', idx: i, w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + scrollY), left: Math.round(r.left + scrollX), bytes: html.length, html: html.length < 60000 ? html : null, inHeader: !!el.closest('header, nav, [class*=logo], [id*=logo]'), aria: el.getAttribute('aria-label') || '' }; });
  const widgets = [...document.querySelectorAll('canvas, iframe, map, [class*="map" i], [id*="map" i], [class*="chart" i], [id*="chart" i], video')].filter(vis).slice(0, 12).map((el, i) => { const r = el.getBoundingClientRect(); return { kind: 'widget', idx: i, tag: el.tagName.toLowerCase(), w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + scrollY), left: Math.round(r.left + scrollX), cls: (el.className || '') + ' ' + (el.id || '') }; });
  const outline = { title: document.title, headings: [...document.querySelectorAll('h1,h2,h3')].slice(0, 40).map(h => ({ tag: h.tagName, text: h.innerText.trim().slice(0, 120) })),
                    nav: [...document.querySelectorAll('nav a, header a')].slice(0, 40).map(a => a.innerText.trim().slice(0, 40)).filter(Boolean),
                    sections: [...document.querySelectorAll('main > *, body > section, body > div')].slice(0, 30).map(s => ({ tag: s.tagName.toLowerCase(), cls: (s.className || '').toString().slice(0, 60), text: (s.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 160) })).filter(s => s.text),
                    height: document.documentElement.scrollHeight, bodyBg: getComputedStyle(document.body).backgroundColor, font: getComputedStyle(document.body).fontFamily.slice(0, 80) };
  const text = (document.body.innerText || '').slice(0, 300000);
  return { imgs, bgs, svgs, widgets, outline, text };
}
"""


def _name(url: str, prefix: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif"):
        ext = ".img"
    return f"{prefix}_{hashlib.sha1(url.encode()).hexdigest()[:10]}{ext}"


def harvest(url: str, out: Path, width: int = 1280, height: int = 800, max_full: int = 2600) -> dict:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    manifest: dict = {"url": url, "images": [], "svgs": [], "widgets": [], "logo": None}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scale, tag in ((1, ""), (2, "@2x")):
            ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale, user_agent=UA, locale="en-US")
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"before{tag}.png"))
            if scale == 1:
                page.screenshot(path=str(out / "before_full.png"), full_page=True, clip={"x": 0, "y": 0, "width": width, "height": min(max_full, page.evaluate("document.documentElement.scrollHeight"))})
                data = page.evaluate(JS_COLLECT)
                live = page.content()
                base = f'<base href="{url}">'
                live = re.sub(r"<head([^>]*)>", lambda m: f"<head{m.group(1)}>{base}", live, count=1, flags=re.I) if re.search(r"<head[^>]*>", live, re.I) else base + live
                (out / "live.html").write_text(live, encoding="utf-8")
                manifest["live_html"] = "live.html"
                manifest["outline"] = data["outline"]
                manifest["text"] = data.get("text", "")
                (out / "page_text.txt").write_text(manifest["text"], encoding="utf-8")
                # images and background images → download
                seen = set()
                for it in data["imgs"] + data["bgs"]:
                    src = urljoin(url, it["src"])
                    if src in seen or src.startswith("data:"):
                        if src.startswith("data:image") and len(src) < 300000:
                            import base64
                            head, b64 = src.split(",", 1)
                            ext = ".svg" if "svg" in head else ".png"
                            p = assets / f"inline_{hashlib.sha1(src.encode()).hexdigest()[:10]}{ext}"
                            p.write_bytes(base64.b64decode(b64) if ";base64" in head else b64.encode())
                            manifest["images"].append({**{k: it[k] for k in ("kind", "w", "h", "top", "left")}, "alt": it.get("alt", ""), "path": f"assets/{p.name}", "src": "data:"})
                        continue
                    seen.add(src)
                    try:
                        r = httpx.get(src, headers={"User-Agent": UA, "Referer": url}, timeout=30, follow_redirects=True)
                        if r.status_code != 200 or not r.headers.get("content-type", "").startswith(("image/", "application/octet")):
                            continue
                        p = assets / _name(src, it["kind"])
                        p.write_bytes(r.content)
                        manifest["images"].append({**{k: it[k] for k in ("kind", "w", "h", "top", "left")}, "alt": it.get("alt", ""), "cls": it.get("cls", "")[:80], "inHeader": it.get("inHeader", False), "path": f"assets/{p.name}", "src": src, "bytes": len(r.content)})
                    except Exception:  # noqa: BLE001
                        continue
                for sv in data["svgs"]:
                    if sv.get("html"):
                        p = assets / f"svg_{sv['idx']}.svg"
                        html = sv["html"]
                        if "xmlns=" not in html[:200]:
                            html = html.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
                        p.write_text(html, encoding="utf-8")
                        manifest["svgs"].append({**{k: sv[k] for k in ("w", "h", "top", "left", "inHeader", "aria")}, "path": f"assets/{p.name}"})
                # element screenshots for maps / canvases / charts / iframes at 2× (from the 2× context below)
                manifest["_widgets_raw"] = data["widgets"]
            else:
                for i, wd in enumerate(manifest.get("_widgets_raw", [])):
                    try:
                        sel = {"canvas": "canvas", "iframe": "iframe", "video": "video"}.get(wd["tag"])
                        loc = page.locator(sel).nth(wd["idx"]) if sel else page.locator('[class*="map" i], [id*="map" i], [class*="chart" i], [id*="chart" i]').nth(wd["idx"])
                        p = assets / f"widget_{i}_{wd['tag']}.png"
                        loc.screenshot(path=str(p), timeout=15000)
                        manifest["widgets"].append({**{k: wd[k] for k in ("tag", "w", "h", "top", "left", "cls")}, "path": f"assets/{p.name}"})
                    except Exception:  # noqa: BLE001
                        continue
            ctx.close()
        browser.close()
    manifest.pop("_widgets_raw", None)
    # logo guess: header image/svg, smallest area wins among header ones; else name match
    cands = [i for i in manifest["images"] if i.get("inHeader")] + [{"path": s["path"], "w": s["w"], "h": s["h"], "alt": s.get("aria", ""), "kind": "svg"} for s in manifest["svgs"] if s.get("inHeader")]
    cands = cands or [i for i in manifest["images"] if re.search(r"logo", (i.get("alt", "") + i.get("cls", "") + i.get("src", "")), re.I)]
    if cands:
        manifest["logo"] = min(cands, key=lambda c: c["w"] * c["h"])["path"]
    (out / "assets" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    m = harvest(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items() if k != "outline"}, indent=1))
    print(json.dumps(m["outline"], ensure_ascii=False)[:800])

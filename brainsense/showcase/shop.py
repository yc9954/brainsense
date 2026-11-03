"""Brain-curated shopping: real products (Amazon catalog on Hugging Face, with price, bullets and specs)
→ TRIBE heads rank what the crowd's cortex wants (aesthetic / appeal / popularity) → Muse adds the
*rational* read of price, specs and catches → one page: "the crowd will want it" vs "reason says wait",
plus 👍/👎 that trains the personal head live (the page talks to the BrainSense server directly).

    uv run python -m brainsense.showcase.shop --category "Home & Kitchen" --n 40
    uv run python -m brainsense.showcase.shop --category "Clothing, Shoes & Jewelry" --n 40 --name fashion
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import time
from pathlib import Path

import httpx
import typer

from ..loop.generate import _client
from .ab import _eval, _score_with_retry
from .skills import area_label, read_brain

app = typer.Typer(add_completion=False)
DS = "bprateek/amazon_product_description"
UA = "BrainSense/0.1 (Meta hackathon demo; contact: alexlee@sweetspot.co.kr)"
MODEL = os.environ.get("BRAINSENSE_LLM_MODEL", "muse-spark-1.3")
SERVER = os.environ.get("BRAINSENSE_SERVER_URL", "http://localhost:8000").rstrip("/")


def fetch_catalog(category: str, n: int, out: Path, max_rows: int = 10000) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for off in range(0, max_rows, 100):
        r = httpx.get("https://datasets-server.huggingface.co/rows", timeout=60,
                      params={"dataset": DS, "config": "default", "split": "train", "offset": off, "length": 100})
        if r.status_code != 200:
            break
        for x in r.json().get("rows", []):
            row = x["row"]
            cat = row.get("Category") or ""
            if not cat.startswith(category) or not row.get("Image") or not row.get("Selling Price"):
                continue
            url = row["Image"].split("|")[0].strip()
            if not url.startswith("http"):
                continue
            iid = "shop_" + hashlib.sha1((row.get("Asin") or row.get("Uniq Id") or url).encode()).hexdigest()[:12]
            path = out / f"{iid}.jpg"
            if not path.exists():
                try:
                    img = httpx.get(url, timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
                    if img.status_code != 200 or len(img.content) < 8000:
                        continue
                    path.write_bytes(img.content)
                except Exception:  # noqa: BLE001
                    continue
            price = re.sub(r"[^0-9.]", "", (row.get("Selling Price") or "").split("-")[0]) or None
            items.append({"id": iid, "name": (row.get("Product Name") or "")[:140], "brand": row.get("Brand Name") or "",
                          "price": float(price) if price else None, "list_price": row.get("List Price") or "",
                          "about": (row.get("About Product") or "")[:900], "specs": (row.get("Product Specification") or "")[:500],
                          "category": cat, "image": path.name, "url": url})
            if len(items) >= n:
                return items
    return items


def crowd_scores(item: dict, img: Path) -> dict:
    sc = _score_with_retry(img, item["id"], None, 0.5)          # brain only, no judge (product photos ≠ UI)
    ev = _eval(item["id"])
    heads = {k: {x: v[x] for x in ("score", "percentile", "confidence")} | {"top": [area_label(f["name"], "en") for f in v.get("top_features", [])[:2]]}
             for k, v in (ev.get("heads") or {}).items() if isinstance(v, dict) and "percentile" in v}
    crit = read_brain(ev, "ad")
    return {"heads": heads, "diagnosis": crit.diagnosis[:2], "crowd_score": sc.ui_score}


def rational_judge(item: dict, heads: dict) -> dict:
    crowd = ", ".join(f"{k} top {100 - v['percentile']:.0f}%" for k, v in heads.items() if k in ("aesthetic", "appeal", "popularity"))
    prompt = (f"You are a rational, slightly skeptical shopping advisor. Judge this product on its facts, not its looks.\n"
              f"Name: {item['name']}\nBrand: {item['brand'] or 'unknown'}\nPrice: ${item['price']}\nList price: {item['list_price'] or '-'}\n"
              f"Bullets: {item['about']}\nSpecs: {item['specs']}\n"
              f"A predicted-human-cortex model says the crowd's gut reaction to the photo is: {crowd}.\n"
              "Reply ONLY with JSON: {\"value_for_money\": 1-5, \"quality_risk\": 1-5 (5 = risky), \"catches\": [\"...\", \"...\"], "
              "\"who_for\": \"...\", \"verdict\": \"buy\" | \"wait\" | \"skip\", \"crowd_vs_reason\": \"one sentence: does the gut reaction match the facts?\"}")
    try:
        r = _client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1500,
                                              extra_body={"reasoning_effort": "low"})
        m = re.search(r"\{.*\}", r.choices[0].message.content or "", re.S)
        d = json.loads(m.group(0)) if m else {}
    except Exception as e:  # noqa: BLE001
        d = {"error": str(e)[:80]}
    return {"value_for_money": d.get("value_for_money"), "quality_risk": d.get("quality_risk"), "catches": d.get("catches", [])[:3],
            "who_for": d.get("who_for", ""), "verdict": d.get("verdict", "wait"), "crowd_vs_reason": d.get("crowd_vs_reason", "")}


@app.command()
def run(category: str = typer.Option("Home & Kitchen"), n: int = typer.Option(40), name: str = typer.Option(""),
        out: Path = typer.Option(Path("results/showcase/shop")), judge: bool = typer.Option(True)):
    slug = name or re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")
    d = out / slug
    print(f"▶ catalog {category} → {d}")
    items = fetch_catalog(category, n, d / "img")
    print(f"  {len(items)} products with images")
    t0 = time.time()
    for i, it in enumerate(items, 1):
        try:
            it.update(crowd_scores(it, d / "img" / it["image"]))
        except Exception as e:  # noqa: BLE001
            print(f"  score failed {it['id']}: {str(e)[:80]}")
            continue
        if judge:
            it["rational"] = rational_judge(it, it["heads"])
        a = it["heads"].get("appeal", {}).get("percentile", 50)
        print(f"  [{i}/{len(items)}] appeal top {100 - a:.0f}% · {it.get('rational', {}).get('verdict', '-')} · {it['name'][:50]} ({time.time() - t0:.0f}s)")
        (d / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    build_page(d, category)
    print(f"  page → {d / 'index.html'}")


def build_page(d: Path, category: str) -> Path:
    items = [i for i in json.loads((d / "items.json").read_text(encoding="utf-8")) if i.get("heads")]
    e = _html.escape
    data = json.dumps([{k: i.get(k) for k in ("id", "name", "price", "image", "heads", "diagnosis", "rational", "url")} for i in items], ensure_ascii=False)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>BrainSense picks · {e(category)}</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:28px}}h1{{font-size:20px;font-weight:600;margin:0 0 4px}}
.sub{{color:#9a9aa6;font-size:13px;max-width:980px}}.tabs{{display:flex;gap:8px;margin:14px 0}}.tabs button{{background:#15151b;border:1px solid #23232b;color:#ccc;padding:7px 12px;border-radius:999px;cursor:pointer;font-size:13px}}
.tabs button.on{{background:#ff6a2b;border-color:#ff6a2b;color:#fff}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}}
.card{{background:#15151b;border:1px solid #23232b;border-radius:14px;overflow:hidden;display:flex;flex-direction:column}}.card img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff}}
.b{{padding:10px 12px;font-size:12.5px;line-height:1.45;flex:1}}.n{{font-weight:600;color:#f3f3f5;font-size:13px;margin-bottom:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.chips{{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}}.chip{{background:#23232b;border-radius:6px;padding:2px 6px;font-size:11px;color:#ccc}}.chip.hot{{background:#3a1d12;color:#ffb38a}}
.v{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;display:inline-block}}.buy{{background:#17391f;color:#7ee787}}.wait{{background:#3a2e12;color:#ffd57a}}.skip{{background:#3a1515;color:#ff7b72}}
.k{{color:#8b8b96}}.fb{{display:flex;gap:6px;padding:0 12px 12px}}.fb button{{flex:1;background:#23232b;border:0;color:#eee;padding:7px;border-radius:8px;cursor:pointer}}.fb button:hover{{background:#2e2e38}}
.me{{font-size:11px;color:#ffb38a;padding:0 12px 10px}}</style></head><body>
<h1>Brain-curated picks — {e(category)}</h1>
<div class=sub>{len(items)} real products (Amazon catalog). <b>Crowd</b> = what a predicted human cortex (TRIBE v2 → calibrated heads) wants from the photo. <b>Reason</b> = Muse reading the price, bullets and specs. 👍/👎 trains <b>your</b> head live (6 votes to switch on) — "the crowd would, but you wouldn't" is the point.</div>
<div class=tabs><button class=on onclick="sortBy('appeal',this)">crowd appeal</button><button onclick="sortBy('aesthetic',this)">crowd aesthetic</button><button onclick="sortBy('popularity',this)">crowd popularity</button><button onclick="sortBy('reason',this)">reason (value)</button><button onclick="sortBy('me',this)">my taste</button></div>
<div class=grid id=grid></div>
<script>
const ITEMS={data}; const SERVER="{SERVER}"; const ME={{}};
const pct=(it,h)=> it.heads&&it.heads[h]? 100-it.heads[h].percentile : 50;
function card(it){{
  const r=it.rational||{{}}; const v=(r.verdict||'wait').toLowerCase();
  const chips=['aesthetic','appeal','popularity'].map(h=>`<span class="chip ${{pct(it,h)<=20?'hot':''}}">${{h}} top ${{pct(it,h).toFixed(0)}}%</span>`).join('');
  const areas=(it.heads.appeal?.top||[]).slice(0,2).map(a=>`<span class=chip>${{a}}</span>`).join('');
  const me=ME[it.id]!=null?`<div class=me>your head: top ${{(100-ME[it.id]).toFixed(0)}}%</div>`:'';
  return `<div class=card data-id="${{it.id}}"><a href="${{it.url}}" target=_blank><img src="img/${{it.image}}"></a><div class=b><div class=n>${{it.name}}</div>
  <div><b>$${{it.price??'?'}}</b> · <span class="v ${{v}}">${{v.toUpperCase()}}</span> <span class=k>value ${{r.value_for_money??'-'}}/5 · risk ${{r.quality_risk??'-'}}/5</span></div>
  <div class=chips>${{chips}}</div><div class=chips>${{areas}}</div>
  <div class=k>${{(r.catches||[]).slice(0,2).join(' · ')}}</div><div style="margin-top:6px">${{r.crowd_vs_reason||''}}</div></div>${{me}}
  <div class=fb><button onclick="vote('${{it.id}}',true)">👍 like</button><button onclick="vote('${{it.id}}',false)">👎 pass</button></div></div>`;
}}
function sortBy(key,btn){{ document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on')); btn&&btn.classList.add('on');
  const arr=[...ITEMS].sort((a,b)=> key==='reason'? ((b.rational?.value_for_money||0)-(a.rational?.value_for_money||0)) : key==='me'? ((ME[b.id]??-1)-(ME[a.id]??-1)) : (pct(a,key)-pct(b,key)));
  document.getElementById('grid').innerHTML=arr.map(card).join(''); }}
async function vote(id,liked){{ try{{ await fetch(SERVER+'/agent/feedback',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{item_id:id,liked}})}});
  for(const it of ITEMS){{ const ev=await (await fetch(SERVER+'/eval/'+it.id)).json(); const p=ev.heads?.personal?.personal; if(p&&p.percentile!=null) ME[it.id]=p.percentile; }}
  const on=document.querySelector('.tabs button.on'); sortBy(on?on.textContent.includes('taste')?'me':on.textContent.split(' ').pop():'appeal', on); }}catch(e){{ alert('BrainSense server not reachable: '+e); }} }}
sortBy('appeal');
</script></body></html>"""
    out = d / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    app()

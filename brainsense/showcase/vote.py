"""Blind human preference page: every finalist pair from the given runs, shuffled and side-swapped,
one click (or ← / →) per pair, then "결과 내보내기" downloads votes.json. No server, no Muse: the
only judge that is not a model. Build after a run; open results/showcase/vote.html in a browser.

    uv run python -m brainsense.showcase.vote results/showcase/suite1 results/showcase/suite2-hybrid
    uv run python -m brainsense.showcase.vote --tally results/showcase/votes.json results/showcase/suite1 ...
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ARM_KO = {"oneshot": "Muse 한 번", "muse_loop": "Muse 자기평가 루프", "brain_loop": "BrainSense 루프", "hybrid_loop": "BrainSense 하이브리드 루프"}


def pairs_from(run_dirs: list[Path], out_dir: Path) -> list[dict]:
    pairs = []
    for rd in run_dirs:
        s = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
        for key, b in s["briefs"].items():
            arms = list(b["final"].items())
            champ = next((a for a in ("hybrid_loop", "brain_loop") if a in b["final"]), None)
            if not champ:
                continue
            for arm, f in arms:
                if arm == champ:
                    continue
                a, c = b["final"][champ], f
                pairs.append({"run": rd.name, "brief_key": key, "brief": b["brief"],
                              "champ": champ, "other": arm,
                              "champ_png": str(Path(a["png"]).resolve().relative_to(out_dir.resolve())),
                              "other_png": str(Path(c["png"]).resolve().relative_to(out_dir.resolve()))})
    random.Random(7).shuffle(pairs)
    for i, p in enumerate(pairs):
        p["swap"] = bool(random.Random(100 + i).random() < 0.5)
    return pairs


def build(run_dirs: list[Path], out: Path) -> Path:
    pairs = pairs_from(run_dirs, out.parent)
    data = json.dumps(pairs, ensure_ascii=False)
    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>BrainSense blind vote</title>
<style>body{{font-family:-apple-system,Pretendard,sans-serif;background:#0b0b0f;color:#eee;margin:0;padding:24px}}
h1{{font-size:18px;font-weight:600;margin:0 0 4px}} .brief{{color:#aaa;font-size:13px;max-width:980px;min-height:36px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:14px}} .c{{cursor:pointer;border:2px solid #23232b;border-radius:14px;overflow:hidden;background:#15151b}}
.c:hover{{border-color:#ffb38a}} .c img{{width:100%;display:block}} .lab{{padding:10px 14px;font-size:14px;color:#ccc}}
.bar{{display:flex;gap:12px;align-items:center;margin-top:14px;font-size:13px;color:#8b8b96}} button{{background:#ff6a2b;border:0;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;cursor:pointer}}
.done{{font-size:15px;line-height:1.6}}</style></head><body>
<h1>어느 쪽이 더 좋은 첫 화면인가요? (클릭 또는 ← →)</h1><div class=brief id=brief></div>
<div class=row><div class=c id=L onclick="vote(0)"><img id=imgL><div class=lab>A</div></div><div class=c id=R onclick="vote(1)"><img id=imgR><div class=lab>B</div></div></div>
<div class=bar><span id=prog></span><button onclick="undo()">되돌리기</button><button onclick="exportVotes()">결과 내보내기 (votes.json)</button><button onclick="showVotes()">결과 여기 표시</button><span id=tally></span></div>
<textarea id=out style="display:none;width:100%;height:160px;margin-top:10px;background:#15151b;color:#ddd;border:1px solid #23232b;border-radius:8px;font-size:12px"></textarea>
<script>
const PAIRS={data}; let i=0; const votes=[];
function show(){{ if(i>=PAIRS.length){{document.querySelector('.row').innerHTML='<div class=done>끝! 결과 내보내기를 눌러 votes.json을 저장한 뒤 `uv run python -m brainsense.showcase.vote --tally votes.json <runs…>` 로 집계하세요.</div>';document.getElementById('brief').textContent='';return;}}
 const p=PAIRS[i]; document.getElementById('brief').textContent=p.brief; const l=p.swap?p.other_png:p.champ_png, r=p.swap?p.champ_png:p.other_png;
 document.getElementById('imgL').src=l; document.getElementById('imgR').src=r; document.getElementById('prog').textContent=(i+1)+' / '+PAIRS.length; tallyNow(); }}
function vote(side){{ const p=PAIRS[i]; const champWins = (side===0) ? !p.swap : p.swap; votes.push({{idx:i,run:p.run,brief_key:p.brief_key,champ:p.champ,other:p.other,champ_wins:champWins}}); i++; show(); }}
function undo(){{ if(!votes.length) return; votes.pop(); i--; show(); }}
function tallyNow(){{ const n=votes.length, w=votes.filter(v=>v.champ_wins).length; document.getElementById('tally').textContent = n? `지금까지 BrainSense ${{w}}/${{n}} 승`:''; }}
function showVotes(){{ const t=document.getElementById('out'); t.style.display='block'; t.value=JSON.stringify(votes,null,1); t.select(); try{{document.execCommand('copy');}}catch(e){{}} }}
function exportVotes(){{ const blob=new Blob([JSON.stringify(votes,null,1)],{{type:'application/json'}}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='votes.json'; a.click(); }}
addEventListener('keydown',e=>{{ if(e.key==='ArrowLeft') vote(0); if(e.key==='ArrowRight') vote(1); }});
show();
</script></body></html>"""
    out.write_text(html, encoding="utf-8")
    return out


def tally(votes_path: Path) -> None:
    votes = json.loads(Path(votes_path).read_text(encoding="utf-8"))
    by = {}
    for v in votes:
        k = f"{v['champ']}_vs_{v['other']}"
        w, n = by.get(k, (0, 0))
        by[k] = (w + bool(v["champ_wins"]), n + 1)
    print("## human blind preference")
    for k, (w, n) in by.items():
        print(f"  {k}: {w}/{n} = {w / n:.0%}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--tally":
        tally(Path(args[1]))
    else:
        runs = [Path(a) for a in args] or [Path("results/showcase/suite1")]
        print(build(runs, Path("results/showcase/vote.html")))

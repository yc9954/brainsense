"""Brain-reading skills: turn a TRIBE/heads evaluation into an *expert visual critique*.

The heads say how good; these rules say *why* in the vocabulary of visual neuroscience and
what a designer should change. Everything is relative within the item (a still frame only moves
the cortex a few tenths of a z-score), so we rank the nine region groups against each other and
look at the time course (hook in the first 2 s vs. the rest) rather than at absolute values.

    from brainsense.showcase.skills import read_brain
    critique = read_brain(eval_json, kind="landing")   # kind: landing | ad | poster | app | video
    critique.prompt_block   -> text for the generator's next round
    critique.diagnosis      -> list[str] Korean one-liners for the UI / README
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

# HCP-MMP1 area codes the heads cite, with the function a designer can act on.
AREA_INFO: dict[str, tuple[str, str]] = {
    "V1": ("1차 시각피질", "contrast, edge density, texture"),
    "V2": ("2차 시각피질", "contrast, texture, local shape"),
    "V3": ("V3", "contours and motion-in-depth"),
    "V4": ("V4 색·형태", "color, curvature, saturation"),
    "MT": ("MT 움직임", "motion / implied motion"),
    "MST": ("MST 움직임", "global motion, flow"),
    "LO1": ("LO 물체 형태", "object silhouettes"), "LO2": ("LO 물체 형태", "object silhouettes"),
    "LO3": ("LO 물체 형태", "object silhouettes"),
    "FFC": ("방추상 얼굴 영역", "faces"), "PIT": ("후측 하측두 물체", "objects, products"),
    "VVC": ("복측 시각 복합체", "objects / faces"),
    "STSva": ("STS 사회 지각", "faces, gaze, social cues"), "STSvp": ("STS 사회 지각", "faces, gaze, social cues"),
    "STSda": ("STS 사회 지각", "biological motion"), "TPOJ1": ("측두두정접합", "social attention"),
    "VMV1": ("장소 영역(PPA)", "scenes, layout"), "VMV2": ("장소 영역(PPA)", "scenes, layout"),
    "VMV3": ("장소 영역(PPA)", "scenes, layout"), "PHA1": ("해마곁 장소", "scenes, depth"),
    "PHA2": ("해마곁 장소", "scenes, depth"), "PHA3": ("해마곁 장소", "scenes, depth"),
    "RSC": ("후부 대상 장소", "spatial layout, navigation"), "POS1": ("두정후두구", "spatial layout"),
    "POS2": ("두정후두구", "spatial layout"),
    "IP0": ("두정내구 주의", "salience map"), "IP1": ("두정내구 주의", "salience map"), "IP2": ("두정내구 주의", "salience map"),
    "LIPv": ("LIP 시선 계획", "where the eye will go"), "LIPd": ("LIP 시선 계획", "where the eye will go"),
    "VIP": ("VIP", "near-space motion"), "AIP": ("AIP 손·물체", "graspable objects"),
    "FEF": ("전두안구영역", "eye-movement planning"), "PEF": ("전운동 안구영역", "eye-movement planning"),
    "10r": ("내측 전전두 10r 보상", "subjective value / wanting"), "10v": ("내측 전전두 10v 보상", "subjective value"),
    "10d": ("내측 전전두 10d", "value, self-relevance"), "25": ("슬하 대상 25", "affect"),
    "s32": ("전대상 32 감정", "affective value"), "p32": ("전대상 32 감정", "affective value"),
    "a24": ("전대상 24", "affect, conflict"), "OFC": ("안와전두 보상", "reward value, liking"),
    "pOFC": ("후측 안와전두 보상", "reward value, liking"), "13l": ("안와전두 13l", "reward"), "11l": ("안와전두 11l", "reward, aesthetics"),
    "44": ("브로카 44 언어", "reading, syntax"), "45": ("브로카 45 언어", "reading, semantics"),
    "55b": ("55b 언어", "language"), "STGa": ("상측두 언어", "speech"), "A4": ("청각 A4", "sound"), "A5": ("청각 A5", "sound"),
    "TE1a": ("측두극 의미", "semantics, concepts"), "TE1m": ("측두 의미", "semantics"), "TE1p": ("측두 의미", "semantics"),
    "STSdp": ("STS 언어", "speech / narrative"), "PSL": ("측두두정 언어", "language"), "SFL": ("상전두 언어", "language"),
    "31pv": ("후대상 기본모드", "mind-wandering, self"), "31pd": ("후대상 기본모드", "mind-wandering, self"),
    "23d": ("후대상 기본모드", "mind-wandering"), "v23ab": ("후대상 기본모드", "mind-wandering"),
    "d23ab": ("후대상 기본모드", "mind-wandering"), "7m": ("설전부 기본모드", "mind-wandering"),
    "PCV": ("설전부 기본모드", "mind-wandering"), "9m": ("내측 전두 기본모드", "self-reference"), "8BM": ("내측 전두 기본모드", "self-reference"),
    "46": ("배외측 전전두 46 통제", "effort, working memory"), "9-46d": ("배외측 전전두 통제", "effort"),
    "p9-46v": ("배외측 전전두 통제", "effort"), "a9-46v": ("배외측 전전두 통제", "effort"),
    "IFSa": ("하전두구 통제", "effort, rule use"), "IFSp": ("하전두구 통제", "effort"), "IFJa": ("하전두접합 통제", "task switching"),
    "IFJp": ("하전두접합 통제", "task switching"), "8C": ("8C 통제", "effort"), "8Av": ("8Av 통제", "attention control"),
    "PoI1": ("후측 뇌섬엽", "interoception, arousal"), "A1": ("1차 청각", "sound (predicted even for stills)"),
    "PFm": ("하두정 PFm", "attention / semantics"), "PGi": ("각회 PGi", "semantic integration"), "PGs": ("각회 PGs", "semantic integration"),
}
GROUP_EN = {
    "visual_early": "early vision (V1–V4)", "visual_motion": "object shape & motion (MT/LO)", "face_body": "faces & people (FFA/STS)",
    "scene_place": "places & scenes (PPA/RSC)", "attention_dorsal": "visual attention (IPS/FEF)", "value_vmpfc": "reward & value (OFC/vmPFC)",
    "language": "language (Broca/STG)", "default_mode": "default mode (mind-wandering)", "control_dlpfc": "cognitive control (dlPFC)",
}
DIAG_EN = {'1차 시각피질이 가장 세게 반응': 'Early visual cortex (V1–V4) fires hardest while the aesthetic head is low: high contrast/texture density reads as clutter', '1차 시각피질이 조용함': 'Early visual cortex is quiet: contrast too weak to pull the eye', '물체 형태(LO)·움직임(MT) 반응이 낮음': 'Object-shape (LO) and motion (MT) areas are low: a text-first screen with no clear object silhouette', '얼굴 영역(FFA/STS)이 조용함': 'Face areas (FFA/STS) are silent: no human or gaze cue', '얼굴 반응은 강한데 주의 헤드가 낮음': 'Face response is strong but the attention head is low: the face pulls the eye away from the CTA', '장소 영역(PPA)이 우세': 'Place areas (PPA/RSC) dominate: the background scene swallows the message', '주의 네트워크(IPS/FEF)가 바쁨': 'Attention network (IPS/FEF) is busy: several candidates compete for the eye', '주의 네트워크가 잠잠함': 'Attention network is quiet: nothing tells the eye where to go', '보상·가치(OFC/vmPFC) 반응이 낮음': "Reward/value areas (OFC/vmPFC) are low: no 'I want this' signal", '보상 회로(OFC/vmPFC)는 켜졌는데 끌림 헤드는 평범': "Reward circuit (OFC/vmPFC) is on but the appeal head is average: value is felt but what is good isn't legible", '언어 영역(브로카/STG)이 바쁨': 'Language areas (Broca/STG) are busy: too much to read', '기본모드 네트워크가 올라옴': 'Default-mode network rises: a familiar, predictable screen → mind-wandering', '인지 통제(dlPFC)가 동원됨': 'Cognitive-control areas (dlPFC) recruited: the structure takes effort to parse'}
GROUP_KO = {
    "visual_early": "1차 시각(V1–V4)", "visual_motion": "움직임·형태(MT/LO)", "face_body": "얼굴·사람(FFA/STS)",
    "scene_place": "장소·배경(PPA/RSC)", "attention_dorsal": "시각 주의(IPS/FEF)", "value_vmpfc": "보상·가치(OFC/vmPFC)",
    "language": "언어(브로카/STG)", "default_mode": "기본모드(딴생각)", "control_dlpfc": "인지 통제(dlPFC)",
}


def area_label(code: str, lang: str = "ko") -> str:
    """'L_pOFC' → '좌 후측 안와전두 보상 (pOFC)' / 'L posterior OFC — reward value, liking (pOFC)'."""
    if lang == "en":
        if "__" in code:
            g, _, st = code.partition("__")
            return f"{GROUP_EN.get(g, g)} {st}"
        hemi = {"L": "L ", "R": "R "}.get(code[:1], "") if code[1:2] == "_" else ""
        base = code[2:] if hemi else code
        info = AREA_INFO.get(base)
        return f"{hemi}{info[1]} ({base})" if info else f"{hemi}{base}"
    if "__" in code:
        g, _, st = code.partition("__")
        stk = {"mean": "평균", "max": "최대", "early": "초반", "late": "후반", "slope": "변화", "std": "변동"}.get(st, st)
        return f"{GROUP_KO.get(g, g)} {stk}"
    hemi = {"L": "좌 ", "R": "우 "}.get(code[:1], "") if code[1:2] == "_" else ""
    base = code[2:] if hemi else code
    info = AREA_INFO.get(base)
    return f"{hemi}{info[0]} ({base})" if info else f"{hemi}{base}"


@dataclass
class Critique:
    kind: str
    ranking: list[tuple[str, float]]            # region group → relative z (within item), high → low
    hook: dict                                   # early vs late attention / visual drive
    diagnosis: list[str] = field(default_factory=list)   # what the cortex says (Korean)
    directives: list[str] = field(default_factory=list)  # what to change next (English, for the generator)
    cited_areas: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)       # region group behind each diagnosis ("" for time-course rules)
    lang: str = "en"

    @property
    def prompt_block(self) -> str:
        lab = GROUP_EN if self.lang == "en" else GROUP_KO
        top = ", ".join(f"{lab[g]} {z:+.2f}" for g, z in self.ranking[:3])
        low = ", ".join(f"{lab[g]} {z:+.2f}" for g, z in self.ranking[-2:])
        lines = ["BRAIN CRITIQUE (TRIBE v2 predicted human cortex while looking at the last render; values are "
                 "relative within this image):",
                 f"- most driven regions: {top}; least: {low}",
                 f"- first-2s hook vs later: attention {self.hook['attention_early']:+.2f} → {self.hook['attention_late']:+.2f}, "
                 f"visual drive {self.hook['visual_early']:+.2f} → {self.hook['visual_late']:+.2f}"]
        if self.cited_areas:
            lines.append("- areas the aesthetic head cites: " + "; ".join(self.cited_areas))
        lines.append("- diagnosis: " + " / ".join(self.diagnosis))
        lines.append("- DO NEXT (highest priority first): " + " ".join(f"({i}) {d}" for i, d in enumerate(self.directives, 1)))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ranking": self.ranking, "hook": self.hook, "diagnosis": self.diagnosis,
                "directives": self.directives, "cited_areas": self.cited_areas, "groups": self.groups}


def _rel(series: dict[str, list[float]]) -> dict[str, np.ndarray]:
    """Group time series standardized across groups (within item) so stills still rank."""
    arr = {g: np.asarray(v, dtype=float) for g, v in series.items() if len(v)}
    if not arr:
        return {}
    allv = np.concatenate(list(arr.values()))
    mu, sd = float(allv.mean()), float(allv.std() or 1.0)
    return {g: (v - mu) / sd for g, v in arr.items()}


def read_brain(ev: dict, kind: str = "landing", lang: str = "en") -> Critique:
    heads = ev.get("heads") or {}
    rel = _rel(ev.get("roi_ts") or {})
    means = {g: float(v.mean()) for g, v in rel.items()}
    ranking = sorted(means.items(), key=lambda kv: -kv[1])
    T = max((len(v) for v in rel.values()), default=0)
    cut = max(1, min(2, T - 1)) if T > 1 else 1

    def early_late(g: str) -> tuple[float, float]:
        v = rel.get(g)
        if v is None or not len(v):
            return 0.0, 0.0
        return float(v[:cut].mean()), float(v[cut:].mean() if len(v) > cut else v.mean())

    ae, al = early_late("attention_dorsal")
    ve, vl = early_late("visual_early")
    hook = {"attention_early": ae, "attention_late": al, "visual_early": ve, "visual_late": vl}

    def pct(h: str) -> float:
        x = heads.get(h) or {}
        return float(x.get("percentile", 50.0))

    aest, attn, appeal = pct("aesthetic"), pct("attention"), pct("appeal")
    rank_of = {g: i for i, (g, _) in enumerate(ranking)}
    # "high"/"low" = in the top/bottom two of the nine groups AND clearly away from the item mean,
    # so a flat cortex does not produce a diagnosis for every group by construction.
    hi = lambda g: rank_of.get(g, 9) <= 1 and means.get(g, 0.0) > 0.45       # noqa: E731
    lo = lambda g: rank_of.get(g, 0) >= len(ranking) - 2 and means.get(g, 0.0) < -0.45   # noqa: E731

    cand: list[tuple[float, str, str, str]] = []   # (salience, diagnosis, directive, group)
    diag: list[str] = []
    todo: list[str] = []
    grps: list[str] = []

    def add(sal: float, d: str, t: str, g: str = "") -> None:
        cand.append((sal, d, t, g))

    def z(g: str) -> float:
        return abs(means.get(g, 0.0))
    # --- early vision: contrast / clutter
    if hi("visual_early") and aest < 50:
        add(z("visual_early") + (0.5 if aest < 50 else 0.0), "1차 시각피질이 가장 세게 반응: 대비·질감 밀도가 높은데 미학 헤드는 낮음 → 어수선함", "Reduce visual noise: one background tone, max 2 accent colors, more whitespace, fewer borders/textures.", "visual_early")
    elif lo("visual_early") and attn < 50:
        add(z("visual_early") + (0.5 if aest < 50 else 0.0), "1차 시각피질이 조용함: 대비가 약해 눈을 끌 자극이 없음", "Raise figure–ground contrast of the hero: darker/lighter backdrop behind the headline, bolder weight, bigger size.", "visual_early")
    # --- objects / motion
    if lo("visual_motion"):
        add(z("visual_motion") + (0.5 if aest < 50 else 0.0), "물체 형태(LO)·움직임(MT) 반응이 낮음: 뚜렷한 사물 실루엣이 없는 텍스트 위주 화면", "Add one dominant object silhouette (product shape, device frame, bold geometric hero) or a diagonal that implies motion.", "visual_motion")
    # --- faces / social
    if lo("face_body") and kind in ("landing", "ad", "poster", "video"):
        add(z("face_body") + (0.5 if aest < 50 else 0.0), "얼굴 영역(FFA/STS)이 조용함: 사람·시선 단서가 없음", "Introduce a human cue: a portrait or illustrated face whose gaze points at the CTA/product (faces win attention fastest).", "face_body")
    elif hi("face_body") and attn < 50:
        add(z("face_body") + (0.5 if aest < 50 else 0.0), "얼굴 반응은 강한데 주의 헤드가 낮음: 얼굴이 CTA가 아닌 곳으로 시선을 끔", "Keep the face but turn its gaze and body orientation toward the headline/CTA; shrink competing imagery.", "face_body")
    # --- scene / layout
    if hi("scene_place") and aest < 60:
        add(z("scene_place") + (0.5 if aest < 50 else 0.0), "장소 영역(PPA)이 우세: 배경 풍경이 화면을 지배해 내용이 묻힘", "Simplify the environment: crop or blur the scene, put copy on a solid panel, let one subject own the frame.", "scene_place")
    # --- attention map
    if hi("attention_dorsal") and aest < 50:
        add(z("attention_dorsal") + (0.5 if aest < 50 else 0.0), "주의 네트워크(IPS/FEF)가 바쁨: 시선을 끄는 후보가 여러 개 → 경쟁", "Make a single focal point: one hero element 2–3× larger than anything else; demote secondary cards and badges.", "attention_dorsal")
    elif lo("attention_dorsal"):
        add(z("attention_dorsal") + (0.5 if aest < 50 else 0.0), "주의 네트워크가 잠잠함: 눈이 갈 곳이 정해지지 않음", "Create an obvious target: strong size hierarchy, a saturated CTA on a calm field, directional cues (arrow, gaze, line) toward it.", "attention_dorsal")
    # --- reward
    if lo("value_vmpfc") or (appeal < 50 and not hi("value_vmpfc")):
        add(z("value_vmpfc") + (0.5 if appeal < 50 else 0.0), "보상·가치(OFC/vmPFC) 반응이 낮음: '갖고 싶다'는 신호가 없음", "Make the benefit concrete and desirable: show the outcome (before/after, real numbers, price or scarcity), warm highlight color on the offer, social proof near the CTA.", "value_vmpfc")
    elif hi("value_vmpfc") and appeal < 50:
        add(z("value_vmpfc") + (0.5 if appeal < 50 else 0.0), "보상 회로(OFC/vmPFC)는 켜졌는데 끌림 헤드는 평범: 가치 신호가 있지만 무엇이 좋은지 읽히지 않음", "Name the value explicitly next to what the eye lands on: one benefit line + price/offer under the hero, nothing else competing.", "value_vmpfc")
    # --- language load
    if hi("language") and attn < 55:
        add(z("language") + (0.5 if aest < 50 else 0.0), "언어 영역(브로카/STG)이 바쁨: 읽을 글자가 너무 많음", "Cut copy: headline ≤ 7 words, one supporting line, one CTA; move details below the fold.", "language")
    # --- default mode
    if hi("default_mode"):
        add(z("default_mode") + (0.5 if aest < 50 else 0.0), "기본모드 네트워크가 올라옴: 익숙하고 예측 가능한 화면 → 딴생각", "Add one unexpected element (asymmetric layout, oversized number, playful illustration, unusual color pairing) so the viewer re-engages.", "default_mode")
    # --- control load
    if hi("control_dlpfc"):
        add(z("control_dlpfc") + (0.5 if aest < 50 else 0.0), "인지 통제(dlPFC)가 동원됨: 구조를 해석하는 데 노력이 듦", "Lower effort: fewer choices on the first screen, consistent grid, one navigation level, clear reading order.", "control_dlpfc")
    # --- time course
    if T > 2 and al < ae - 0.15:
        add(abs(ae - al) + 0.6, f"주의 반응이 첫 2초 이후 꺼짐 ({ae:+.2f} → {al:+.2f}): 첫인상 뒤에 볼 게 없음", "Add a second discovery after the hero (a detail reveal, micro-illustration, or a strong secondary block) so interest holds past 2 s.")
    elif T > 2 and ae < al - 0.15:
        add(abs(ae - al) + 0.6, f"첫 2초 후킹이 약함 ({ae:+.2f} → {al:+.2f})", "Front-load the hook: the single strongest visual must be visible immediately at the top-left/center, not after a scroll or animation.")
    cited = []
    for h in ("aesthetic", "attention", "appeal"):
        for f in (heads.get(h) or {}).get("top_features", [])[:2]:
            cited.append(f"{'▲' if f['contribution'] >= 0 else '▼'} {area_label(f['name'], lang)} [{h}]")
    def tr(d: str) -> str:
        if lang != "en":
            return d
        for ko, en in DIAG_EN.items():
            if d.startswith(ko):
                tail = d[len(ko):]
                m = re.search(r"\(([-+]\d\.\d+ → [-+]\d\.\d+)\)", tail)
                return en + (f" ({m.group(1)})" if m else "")
        if d.startswith("주의 반응이 첫 2초 이후 꺼짐"):
            m = re.search(r"\(([^)]*)\)", d)
            return f"Attention drops after the first 2 s ({m.group(1) if m else ''}): nothing to look at after the first impression"
        if d.startswith("첫 2초 후킹이 약함"):
            m = re.search(r"\(([^)]*)\)", d)
            return f"Weak hook in the first 2 s ({m.group(1) if m else ''})"
        return d

    for _, d, t, g in sorted(cand, key=lambda x: -x[0]):
        diag.append(tr(d))
        todo.append(t)
        grps.append(g)
    if not diag:
        diag.append("No clear bottleneck: keep the structure, refine typography rhythm, spacing and color temperature" if lang == "en"
                    else "눈에 띄는 병목 없음: 현재 구성을 유지하고 디테일(타이포 리듬, 여백, 색 온도)만 다듬을 것")
        todo.append("Keep the structure; refine typography rhythm, spacing scale and color temperature only.")
    # keep the generator focused: 4 directives max, weakest head first
    return Critique(kind=kind, ranking=ranking, hook=hook, diagnosis=diag[:5], directives=todo[:4], cited_areas=cited[:4], groups=grps[:5], lang=lang)

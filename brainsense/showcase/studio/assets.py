"""Poly Haven (CC0, no key) asset client for the photoreal interior loop: curated catalog of indoor
models (with real dimensions), PBR textures for floor/walls/fabric, and HDRIs for the world light.
Everything is cached under assets/polyhaven/ so a run only downloads what the scene spec uses."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

API = "https://api.polyhaven.com"
H = {"User-Agent": "BrainSense/0.1 (Meta hackathon demo; contact: alexlee@sweetspot.co.kr)"}
ROOT = Path(__file__).resolve().parents[3] / "assets" / "polyhaven"
INDOOR_CATS = {"furniture", "seating", "table", "lighting", "decorative", "vases", "books", "shelves", "plants", "dishes", "office", "appliances", "electronics", "textiles", "containers"}
OUTDOOR_WORDS = re.compile(r"rock|tree|stump|log|boulder|grass|cliff|barrel|crate|wrench|hammer|saw|drill|shovel|tool|pipe|rail|anchor|rope|fish|boat|cannon|tire|wheel|cable|pallet|cinder|brick|bucket|concrete|industrial|mushroom|fern|iceplant|succulent|cactus|dead|weed|stone|coral|ship|street|dumpster|trash|garbage|scaffold|fence|gate|lamp_post|streetlight|fire_hydrant|traffic|manhole|sign|debris|dandelion|celandine|sapling|branch|didelta|quiver|spinosa|picnic|monobloc|worn_metal|outdoor|gothic|barber|school|medieval|cowboy", re.I)


def _get(url: str, **params) -> dict:
    return httpx.get(url, params=params, headers=H, timeout=60).json()


def catalog(kind: str = "models", refresh: bool = False) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    p = ROOT / f"catalog_{kind}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text())
    data = _get(f"{API}/assets", t=kind)
    p.write_text(json.dumps(data))
    return data


def indoor_models(limit: int = 110) -> list[dict]:
    """Curated shortlist Muse can pick from: id, name, categories, dimensions in metres."""
    out = []
    for k, v in catalog("models").items():
        cats = set(v.get("categories", []))
        if not cats & INDOOR_CATS or OUTDOOR_WORDS.search(k + " " + v["name"]):
            continue
        if any(c.startswith("collection: ") and c.split(": ")[1] in ("project_lighthouse", "the_shed", "hidden_alley", "smugglers_cove", "namaqualand", "pine_forest", "verdant_trail") for c in cats) and not cats & {"furniture", "seating", "table", "lighting", "plants", "decorative", "vases", "books"}:
            continue
        dims = v.get("dimensions") or [0, 0, 0]
        out.append({"id": k, "name": v["name"], "cats": sorted(c for c in cats if not c.startswith("collection")), "dims_m": [round(d / 1000, 2) for d in dims], "tags": v.get("tags", [])[:6]})
    # furniture first, then lighting/plants/decor, then the rest
    rank = lambda m: (0 if {"furniture", "seating", "table"} & set(m["cats"]) else 1 if {"lighting", "plants", "shelves"} & set(m["cats"]) else 2)  # noqa: E731
    out.sort(key=lambda m: (rank(m), m["id"]))
    return out[:limit]


CURATED_TEXTURES = {
    "floor": ["herringbone_parquet", "diagonal_parquet", "laminate_floor_02", "laminate_floor_03", "oak_veneer_01", "embedded_plank_flooring", "brown_planks_09", "hinoki_planks", "japanese_cedar_planks", "marble_01", "concrete_floor_02", "large_floor_tiles_02", "wood_floor_deck", "wood_floor"],
    "wall": ["beige_wall_001", "beige_wall_002", "grey_plaster", "grey_plaster_02", "clay_plaster", "blue_plaster_wall", "concrete_wall_001", "bamboo_wall_02", "painted_plaster_wall", "plastered_wall_04"],
    "fabric": ["fabric_pattern_07", "fabric_leather_01", "leather_white", "brown_leather", "denim_fabric"],
}
CURATED_HDRIS = {
    "daylight (through the window)": ["belfast_open_field", "cloudy_vondelpark", "eilenriede_park", "citrus_orchard_puresky", "drackenstein_quarry_puresky", "evening_meadow", "autumn_park", "courtyard", "bloem_field_sunrise", "kloofendal_48d_partly_cloudy_puresky"],
    "indoor ambience": ["art_studio", "blocky_photo_studio", "brown_photostudio_02", "empty_play_room", "entrance_hall", "studio_small_09"],
}


def indoor_textures(limit: int = 40) -> list[dict]:
    want = re.compile(r"wood|floor|plank|parquet|plaster|wall|paint|fabric|linen|concrete|tile|marble|terrazzo|carpet|leather|oak", re.I)
    out = [{"id": k, "name": v["name"], "cats": v.get("categories", [])[:4]} for k, v in catalog("textures").items() if want.search(k + " " + v["name"]) and not re.search(r"rock|moss|mud|grass|bark|snow|sand|dirt|gravel|rust", k, re.I)]
    return out[:limit]


def indoor_hdris(limit: int = 25) -> list[dict]:
    out = []
    for k, v in catalog("hdris").items():
        cats = set(v.get("categories", []))
        if cats & {"indoor", "studio"} or (cats & {"skies", "urban", "nature"} and v.get("evs", 0) and 8 <= v.get("evs", 0) <= 16 and "night" not in cats):
            out.append({"id": k, "name": v["name"], "cats": sorted(cats)[:4], "evs": v.get("evs"), "whitebalance": v.get("whitebalance")})
    pri = lambda h: (0 if "indoor" in h["cats"] else 1 if "studio" in h["cats"] else 2)  # noqa: E731
    out.sort(key=pri)
    return out[:limit]


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    with httpx.stream("GET", url, headers=H, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    return dest


def fetch_model(asset_id: str, res: str = "1k") -> Path:
    """glTF + its textures/bin into assets/polyhaven/models/<id>/; returns the .gltf path."""
    d = ROOT / "models" / asset_id
    gltf = next(d.glob("*.gltf"), None)
    if gltf:
        return gltf
    files = _get(f"{API}/files/{asset_id}")
    g = files["gltf"].get(res) or files["gltf"][sorted(files["gltf"])[0]]
    entry = g["gltf"]
    main = _download(entry["url"], d / Path(entry["url"]).name)
    for rel, inc in (entry.get("include") or {}).items():
        _download(inc["url"], d / rel)
    return main


def fetch_texture(asset_id: str, res: str = "1k") -> dict:
    """diffuse / roughness / normal (GL) jpgs into assets/polyhaven/textures/<id>/."""
    d = ROOT / "textures" / asset_id
    files = _get(f"{API}/files/{asset_id}")
    out = {}
    for key, name in (("Diffuse", "diff"), ("Rough", "rough"), ("nor_gl", "nor"), ("Displacement", "disp"), ("arm", "arm")):
        node = files.get(key, {}).get(res)
        if not node:
            continue
        fmt = node.get("jpg") or node.get("png") or next(iter(node.values()))
        out[name] = str(_download(fmt["url"], d / Path(fmt["url"]).name))
    return out


def fetch_hdri(asset_id: str, res: str = "2k") -> Path:
    files = _get(f"{API}/files/{asset_id}")
    node = files["hdri"].get(res) or files["hdri"][sorted(files["hdri"])[0]]
    fmt = node.get("hdr") or node.get("exr")
    return _download(fmt["url"], ROOT / "hdri" / Path(fmt["url"]).name)


def catalog_text() -> str:
    """Compact text for the planner prompt (curated textures/HDRIs; all known-good on Poly Haven)."""
    T = catalog("textures")
    Hh = catalog("hdris")
    ms = "\n".join(f"- {m['id']} ({m['name']}; {'/'.join(m['cats'][:3])}; {m['dims_m'][0]}×{m['dims_m'][1]}×{m['dims_m'][2]} m)" for m in indoor_models())
    ts = "\n".join(f"- {k}: {', '.join(t for t in v if t in T)}" for k, v in CURATED_TEXTURES.items())
    hs = "\n".join(f"- {k}: {', '.join(h for h in v if h in Hh)}" for k, v in CURATED_HDRIS.items())
    return f"MODELS (id (name; categories; w×d×h in metres)):\n{ms}\n\nTEXTURES by use:\n{ts}\n\nHDRIS by use:\n{hs}"


if __name__ == "__main__":
    print(catalog_text()[:3000])

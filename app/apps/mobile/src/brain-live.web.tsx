import { useEffect, useMemo, useRef, useState } from "react";
import { Image, Pressable, Text, View } from "react-native";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { BRAINSENSE_URL, ROI_KO, type VertexTs } from "./brainsense-api";

/**
 * Live cortex (web), in the look of the TRIBE v2 teaser: a translucent human head turning a full
 * 360°, the real fsaverage5 pial surface inside it (same MRI frame, so they line up), and TRIBE's
 * per-vertex predictions lighting the cortex up second by second. Pure three.js on a DOM canvas;
 * native falls back to the server-rendered frames (brain-live.tsx).
 */
type Mesh = { nv: number; pos: Float32Array; idx: Uint16Array; sulc?: Uint8Array };
const cache = new Map<string, Promise<Mesh>>();

function parseMesh(buf: ArrayBuffer, withSulc: boolean): Mesh {
  const dv = new DataView(buf);
  const hl = dv.getUint32(0, true);
  const hdr = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl))) as {
    nv: number;
    nf: number;
  };
  let o = 4 + hl;
  const pos = new Float32Array(buf.slice(o, o + hdr.nv * 12));
  o += hdr.nv * 12;
  const idx = new Uint16Array(buf.slice(o, o + hdr.nf * 6));
  o += hdr.nf * 6;
  const sulc = withSulc ? new Uint8Array(buf.slice(o, o + hdr.nv)) : undefined;
  return { nv: hdr.nv, pos, idx, sulc };
}
function loadMesh(name: string, withSulc: boolean): Promise<Mesh> {
  let p = cache.get(name);
  if (!p) {
    p = fetch(`${BRAINSENSE_URL}/assets/${name}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then((b) => parseMesh(b, withSulc));
    cache.set(name, p);
  }
  return p;
}

function decodeU8(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// TRIBE site colormap: grey cortex → red (most of the active patch) → orange → yellow → white-hot peak
function hot(a: number, out: [number, number, number]) {
  if (a < 0.5) {
    const k = a / 0.5;
    out[0] = 0.8 + 0.2 * k;
    out[1] = 0.06 + 0.1 * k;
    out[2] = 0.04;
  } else if (a < 0.85) {
    const k = (a - 0.5) / 0.35;
    out[0] = 1;
    out[1] = 0.16 + 0.64 * k;
    out[2] = 0.04;
  } else {
    const k = (a - 0.85) / 0.15;
    out[0] = 1;
    out[1] = 0.8 + 0.2 * k;
    out[2] = 0.04 + 0.8 * k;
  }
}

export function BrainLive({
  vertexTs,
  series,
  frames,
  stimulusUri,
  stimulusText,
  kind,
  height = 320,
}: {
  vertexTs?: VertexTs;
  series?: Record<string, number[]>;
  frames?: string[];
  stimulusUri?: string;
  stimulusText?: string;
  kind?: string;
  height?: number;
}) {
  const host = useRef<View>(null);
  const [sec, setSec] = useState(0);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [showHead, setShowHead] = useState(true);
  const headVisible = useRef(true);
  headVisible.current = showHead;
  const T = vertexTs?.t ?? 0;

  useEffect(() => {
    const el = host.current as unknown as HTMLDivElement | null;
    if (!el || !vertexTs) return;
    let disposed = false;
    let raf = 0;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping; // keep the reds red: no filmic desaturation
    renderer.toneMappingExposure = 1.0;
    Object.assign(renderer.domElement.style, { width: "100%", height: "100%", display: "block" });
    renderer.domElement.dataset.cortex = "v7";
    el.appendChild(renderer.domElement);

    // Same recipe as Meta's TRIBE v2 viewer: room-environment IBL + ACES, a white rough cortex,
    // and a 7 %-opacity head that reads as a dark-grey bust on black.
    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const camera = new THREE.PerspectiveCamera(45, 1, 1, 5000);
    camera.up.set(0, 0, 1);
    camera.position.set(-330, 0, 22);
    camera.lookAt(0, 0, -12);
    scene.add(new THREE.AmbientLight(0xffffff, 0.12));
    const key = new THREE.DirectionalLight(0xffffff, 0.55);
    key.position.set(-300, 400, 200);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.2);
    fill.position.set(300, -200, -400);
    scene.add(fill);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6a6a6a, 0.22));
    const group = new THREE.Group(); // the whole bust turns together
    scene.add(group);

    const resize = () => {
      const w = el.clientWidth || 520;
      const h = el.clientHeight || height;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : undefined;
    ro?.observe(el);

    const raw = decodeU8(vertexTs.u8);
    const n = vertexTs.n;
    // Smooth each second's map over the mesh (two 1-ring passes) so hot spots read as fMRI blobs
    // like the site's face-coloured maps, not as per-vertex speckle. Filled in once the mesh loads.
    let u8 = raw;
    const smoothOnMesh = (idx: Uint16Array, nv: number) => {
      const deg = new Uint16Array(nv);
      const nbrStart = new Uint32Array(nv + 1);
      for (let i = 0; i < idx.length; i += 3) {
        const a = idx[i];
        const b = idx[i + 1];
        const c = idx[i + 2];
        deg[a] += 2;
        deg[b] += 2;
        deg[c] += 2;
      }
      for (let i = 0; i < nv; i++) nbrStart[i + 1] = nbrStart[i] + deg[i];
      const nbr = new Uint16Array(nbrStart[nv]);
      const fill = new Uint32Array(nv);
      for (let i = 0; i < idx.length; i += 3) {
        const a = idx[i];
        const b = idx[i + 1];
        const c = idx[i + 2];
        nbr[nbrStart[a] + fill[a]++] = b;
        nbr[nbrStart[a] + fill[a]++] = c;
        nbr[nbrStart[b] + fill[b]++] = a;
        nbr[nbrStart[b] + fill[b]++] = c;
        nbr[nbrStart[c] + fill[c]++] = a;
        nbr[nbrStart[c] + fill[c]++] = b;
      }
      const T0 = vertexTs.t;
      let src = new Float32Array(raw.length);
      for (let i = 0; i < raw.length; i++) src[i] = raw[i];
      let dst = new Float32Array(raw.length);
      for (let pass = 0; pass < 2; pass++) {
        for (let f = 0; f < T0; f++) {
          const off = f * n;
          for (let v = 0; v < Math.min(n, nv); v++) {
            let acc = src[off + v] * 2;
            let cnt = 2;
            for (let k = nbrStart[v]; k < nbrStart[v + 1]; k++) {
              acc += src[off + nbr[k]];
              cnt++;
            }
            dst[off + v] = acc / cnt;
          }
        }
        const t = src;
        src = dst;
        dst = t;
      }
      const out = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) out[i] = src[i];
      return out;
    };
    // Hot spots are relative to this item: warm from the 72nd percentile of vertex-seconds, white-hot at 99.5 %.
    let onQ = 0;
    let satQ = 255;
    const computeRange = () => {
      const sample = new Uint8Array(Math.min(u8.length, 80000));
      const stride = Math.max(1, Math.floor(u8.length / sample.length));
      for (let i = 0; i < sample.length; i++) sample[i] = u8[i * stride];
      sample.sort();
      const q = (p: number) => sample[Math.min(sample.length - 1, Math.floor(p * sample.length))];
      onQ = q(0.76);
      satQ = Math.max(onQ + 10, q(0.997));
    };
    const tmp: [number, number, number] = [0, 0, 0];

    let headMesh: THREE.Mesh | undefined;
    Promise.all([loadMesh("fsaverage5_pial.bin", true), loadMesh("fsaverage_head.bin?v=6", false)])
      .then(([brain, head]) => {
        if (disposed) return;
        u8 = smoothOnMesh(brain.idx, brain.nv);
        computeRange();
        // centre on the brain (the head asset is already expressed in that frame)
        const pos = brain.pos;
        let cx = 0;
        let cy = 0;
        let cz = 0;
        for (let i = 0; i < brain.nv; i++) {
          cx += pos[i * 3];
          cy += pos[i * 3 + 1];
          cz += pos[i * 3 + 2];
        }
        cx /= brain.nv;
        cy /= brain.nv;
        cz /= brain.nv;
        const bpos = new Float32Array(pos.length);
        for (let i = 0; i < brain.nv; i++) {
          bpos[i * 3] = pos[i * 3] - cx;
          bpos[i * 3 + 1] = pos[i * 3 + 1] - cy;
          bpos[i * 3 + 2] = pos[i * 3 + 2] - cz;
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(bpos, 3));
        geo.setIndex(new THREE.BufferAttribute(brain.idx, 1));
        geo.computeVertexNormals();
        const col = new Float32Array(brain.nv * 3);
        const colAttr = new THREE.BufferAttribute(col, 3);
        colAttr.setUsage(THREE.DynamicDrawUsage);
        geo.setAttribute("color", colAttr);
        const brainMesh = new THREE.Mesh(
          geo,
          new THREE.MeshStandardMaterial({ color: 0xffffff, vertexColors: true, roughness: 0.85, metalness: 0, envMapIntensity: 0.05 }),
        );
        brainMesh.renderOrder = 1;
        group.add(brainMesh);

        const hgeo = new THREE.BufferGeometry();
        hgeo.setAttribute("position", new THREE.BufferAttribute(head.pos, 3));
        hgeo.setIndex(new THREE.BufferAttribute(head.idx, 1));
        hgeo.computeVertexNormals();
        headMesh = new THREE.Mesh(
          hgeo,
          new THREE.MeshStandardMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.1,
            depthWrite: false,
            depthTest: false,
            side: THREE.DoubleSide,
            roughness: 1,
            metalness: 0,
            envMapIntensity: 0,
          }),
        );
        headMesh.renderOrder = 0;
        group.add(headMesh);
        setReady(true);

        const sulc = brain.sulc as Uint8Array;
        const t0 = performance.now();
        let lastSec = -1;
        const paint = (tau: number) => {
          const f0 = Math.floor(tau) % T;
          const f1 = (f0 + 1) % T;
          const w = tau - Math.floor(tau);
          const smooth = w * w * (3 - 2 * w);
          for (let i = 0; i < Math.min(n, brain.nv); i++) {
            const v = u8[f0 * n + i] * (1 - smooth) + u8[f1 * n + i] * smooth;
            const a = Math.min(1, Math.max(0, (v - onQ) / (satQ - onQ)));
            const base = 0.72 + (sulc[i] / 255 - 0.5) * 0.24;
            // reach full colour quickly (the banner is mostly saturated red with yellow/white peaks)
            const r = Math.min(1, a / 0.04); // hard-edged like the site: grey, then red
            const k = r * r * (3 - 2 * r);
            hot(a, tmp);
            col[i * 3] = base * (1 - k) + tmp[0] * k;
            col[i * 3 + 1] = base * (1 - k) + tmp[1] * k;
            col[i * 3 + 2] = base * (1 - k) + tmp[2] * k;
          }
          colAttr.needsUpdate = true;
        };
        const tick = () => {
          if (disposed) return;
          const t = (performance.now() - t0) / 1000;
          const tau = T > 1 ? (t * 0.8) % T : 0;
          paint(tau);
          const sNow = Math.floor(tau);
          if (sNow !== lastSec) {
            lastSec = sNow;
            setSec(sNow);
          }
          group.rotation.z = (t * 0.2) % (Math.PI * 2); // one full turn every ~31 s
          if (headMesh) headMesh.visible = headVisible.current;
          renderer.render(scene, camera);
          raf = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro?.disconnect();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [vertexTs, T, height]);

  const hottest = useMemo(() => {
    if (!series) return undefined;
    return Object.entries(series)
      .map(([k, v]) => [k, v[Math.min(sec, v.length - 1)] ?? 0] as const)
      .sort((a, b) => b[1] - a[1])[0];
  }, [series, sec]);

  if (!vertexTs) {
    if (frames?.length)
      return (
        <View style={{ borderRadius: 16, overflow: "hidden", backgroundColor: "#fff", aspectRatio: 2.1 }}>
          <Image
            source={{ uri: `data:image/png;base64,${frames[Math.min(sec, frames.length - 1)]}` }}
            resizeMode="contain"
            style={{ width: "100%", height: "100%" }}
          />
        </View>
      );
    return null;
  }

  return (
    <View style={{ backgroundColor: "#000000", borderRadius: 20, overflow: "hidden" }}>
      {/* header: stimulus | prediction */}
      <View style={{ flexDirection: "row", alignItems: "stretch", padding: 14, paddingBottom: 0, gap: 14 }}>
        {stimulusUri && kind !== "audio" ? (
          <View style={{ gap: 6 }}>
            <Text style={lbl}>STIMULUS</Text>
            <Image
              source={{ uri: stimulusUri }}
              style={{ width: 88, height: 60, borderRadius: 9, backgroundColor: "#141418" }}
              resizeMode="cover"
            />
          </View>
        ) : kind === "text" && stimulusText ? (
          <View style={{ gap: 6, width: 150 }}>
            <Text style={lbl}>STIMULUS · TEXT</Text>
            <Text
              numberOfLines={3}
              style={{ color: "rgba(255,255,255,0.78)", fontSize: 11.5, lineHeight: 15, fontStyle: "italic" }}
            >
              “{stimulusText}”
            </Text>
          </View>
        ) : kind === "audio" ? (
          <View style={{ gap: 6 }}>
            <Text style={lbl}>STIMULUS · AUDIO</Text>
            <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 2, height: 36 }}>
              {Array.from({ length: 14 }, (_, i) => (
                <View
                  key={i}
                  style={{
                    width: 4,
                    borderRadius: 2,
                    height: 8 + ((i * 7919) % 26),
                    backgroundColor: i <= (sec / Math.max(1, T)) * 14 ? "#FF7A3D" : "rgba(255,255,255,0.25)",
                  }}
                />
              ))}
            </View>
          </View>
        ) : null}
        <View style={{ flex: 1, gap: 6, justifyContent: "flex-start" }}>
          <Text style={lbl}>MODEL PREDICTION · TRIBE v2</Text>
          <Text style={{ color: "#F5F5F7", fontSize: 14, lineHeight: 20, fontWeight: "500" }}>
            {hottest
              ? `Most active: ${ROI_KO[hottest[0]] ?? hottest[0]}`
              : kind === "text"
                ? "Predicted cortex while reading"
                : kind === "audio"
                  ? "Predicted cortex while listening"
                  : "Predicted cortical response"}
          </Text>
          <Text style={{ color: "rgba(255,255,255,0.5)", fontSize: 12, lineHeight: 16 }}>
            {sec + 1} / {T} s · 20,484 vertices · 1 Hz · predicted fMRI
          </Text>
        </View>
        <Pressable
          onPress={() => setShowHead((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel="Toggle head"
          style={({ pressed }) => ({
            alignSelf: "flex-start",
            paddingHorizontal: 10,
            paddingVertical: 6,
            borderRadius: 999,
            backgroundColor: pressed ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.09)",
          })}
        >
          <Text style={[lbl, { color: "rgba(255,255,255,0.8)", letterSpacing: 0.6 }]}>
            {showHead ? "HEAD ON" : "HEAD OFF"}
          </Text>
        </Pressable>
      </View>
      <View style={{ height, position: "relative" }}>
        <View ref={host} style={{ position: "absolute", inset: 0 }} />
        {!ready && !error ? (
          <Text style={[lbl, { position: "absolute", left: 16, bottom: 12 }]}>Loading the cortex mesh…</Text>
        ) : null}
        {error ? (
          <Text style={[lbl, { position: "absolute", left: 16, bottom: 12, color: "#FF8A80" }]}>
            3D render failed: {error}
          </Text>
        ) : null}
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 14, paddingTop: 4, gap: 5 }}>
        {Array.from({ length: T }, (_, i) => (
          <View
            key={i}
            style={{
              flex: 1,
              height: 3,
              borderRadius: 2,
              backgroundColor: i <= sec ? "#FF7A3D" : "rgba(255,255,255,0.13)",
            }}
          />
        ))}
        <Text style={[lbl, { marginLeft: 8 }]}>fsaverage5</Text>
      </View>
    </View>
  );
}

const lbl = {
  color: "rgba(255,255,255,0.5)",
  fontSize: 10.5,
  letterSpacing: 1.6,
  fontWeight: "700" as const,
};

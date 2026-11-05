"""Builds the NeuroMuse demo video from the real app recordings, renders and figures.

    uv run python scripts/demo/build.py /tmp/demo        # cards from scripts/demo/cards.mjs must already be in /tmp/demo
Output: docs/video/neuromuse-demo.mp4 (1920x1080, 30 fps, narration + quiet pad).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARDS = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/demo")
SEG = CARDS / "seg"
SEG.mkdir(exist_ok=True)
FPS = 30
VOICE, RATE = "Samantha", "176"
FADE = 0.35


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd)[:300]}\n{r.stderr[-1500:]}")


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip())


NARRATION = ROOT / "scripts" / "demo" / "narration-elevenlabs.mp3"
_CHUNKS: list[tuple[float, float]] = []


def _chunks() -> list[tuple[float, float]]:
    """Scene boundaries in the ElevenLabs narration: the 15 longest pauses (the [long pause] tags)."""
    if _CHUNKS:
        return _CHUNKS
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(NARRATION), "-af", "silencedetect=noise=-38dB:d=0.55", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    import re
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    gaps = sorted(sorted(zip(st, en), key=lambda g: -(g[1] - g[0]))[:15])
    total = dur(NARRATION)
    starts = [0.0] + [e - 0.08 for _, e in gaps]
    ends = [s0 + 0.15 for s0, _ in gaps] + [total]
    _CHUNKS.extend(zip(starts, ends))
    return _CHUNKS


_voice_i = [0]
# lines voiced separately (same ElevenLabs voice): name -> (file, end seconds, tempo)
EXTRA_VO = {"s14_arch": (ROOT / "scripts" / "demo" / "narration-arch.mp3", 20.95, 1.08)}


def vo(name: str, text: str) -> tuple[Path | None, float]:
    if not text:
        return None, 0.0
    if name in EXTRA_VO:
        src, end, tempo = EXTRA_VO[name]
        wav = SEG / f"{name}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-t", f"{end:.3f}", "-i", str(src), "-af", f"atempo={tempo}", "-ar", "48000", "-ac", "2", str(wav)])
        return wav, dur(wav)
    if NARRATION.exists():
        a, b = _chunks()[_voice_i[0]]
        _voice_i[0] += 1
        wav = SEG / f"{name}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(NARRATION), "-ar", "48000", "-ac", "2", str(wav)])
        return wav, dur(wav)
    aiff, wav = SEG / f"{name}.aiff", SEG / f"{name}.wav"
    subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(aiff), text], check=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(wav)])
    return wav, dur(wav)


ENC = ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-an"]


def fades(d: float) -> str:
    return f"fade=t=in:st=0:d={FADE},fade=t=out:st={d - FADE:.2f}:d={FADE}"


def card(name: str, png: Path, d: float, zoom: bool = False) -> Path:
    out = SEG / f"{name}.mp4"
    n = int(d * FPS)
    z = f"zoompan=z='1+0.035*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=1920x1080:fps={FPS}," if zoom else ""
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", f"{d:.2f}",
         "-vf", f"scale=1920:1080,{z}{fades(d)}", *ENC, str(out)])
    return out


def clip(name: str, src: Path, d: float, label: Path | None, speed: float = 1.0, start: float = 0.0) -> Path:
    out = SEG / f"{name}.mp4"
    area = "scale=1920:940:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:8:black" if label else \
           "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
    base = (f"[0:v]trim=start={start},setpts=(PTS-STARTPTS)/{speed},fps={FPS},{area},"
            f"tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}")
    if label:
        fc = f"{base}[v];[v][1:v]overlay=0:0,{fades(d)}[o]"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-i", str(label), "-filter_complex", fc, "-map", "[o]", *ENC, str(out)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", f"{base},{fades(d)}[o]", "-map", "[o]", *ENC, str(out)])
    return out


LEFT_W = 1270


def left(name: str, src: Path, d: float, panel: Path, speed: float = 1.0, still: bool = False) -> Path:
    """Footage or a still fitted into the left 2/3, the evidence panel on the right third."""
    out = SEG / f"{name}.mp4"
    inp = ["-loop", "1", "-framerate", str(FPS), "-i", str(src)] if still else ["-i", str(src)]
    v = (f"[0:v]setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale={LEFT_W}:1000:force_original_aspect_ratio=decrease,"
         f"pad=1920:1080:24+({LEFT_W}-iw)/2:(1080-ih)/2:black,tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}")
    fc = f"{v}[v];[v][1:v]overlay=0:0,{fades(d)}[o]"
    run(["ffmpeg", "-y", "-loglevel", "error", *inp, "-i", str(panel), "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def pair(name: str, a: Path, b: Path, d: float, panel: Path) -> Path:
    """Before and after side by side on the left, the panel on the right; the kept side framed in red."""
    out = SEG / f"{name}.mp4"
    w = 620
    h = int(800 * w / 1280)
    y = (1080 - h) // 2
    fc = (f"color=c=black:s=1920x1080:r={FPS}:d={d:.2f}[bg];[0:v]scale={w}:{h}[a];[1:v]scale={w}:{h}[b];"
          f"[bg][a]overlay=24:{y}[t1];[t1][b]overlay={24 + w + 24}:{y}[t2];"
          f"[t2]drawbox=x={24 + w + 24}:y={y}:w={w}:h={h}:color=0xC0504D@1:t=4[t3];[t3][2:v]overlay=0:0,{fades(d)}[o]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(a), "-loop", "1", "-i", str(b), "-i", str(panel),
         "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def phones(name: str, left: Path, right: Path, d: float, lspeed: float, rspeed: float, lab: Path) -> Path:
    """Two phone recordings side by side on black, each with a small caption above."""
    out = SEG / f"{name}.mp4"
    h = 900
    w = int(430 * h / 860)
    h = 890
    xl, xr = 1310 // 2 - w - 24, 1310 // 2 + 24
    y = 95
    fc = (f"color=c=black:s=1920x1080:r={FPS}:d={d:.2f}[bg];"
          f"[0:v]setpts=PTS/{lspeed},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:0:0,tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}[a];"
          f"[1:v]setpts=PTS/{rspeed},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:0:0,tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}[b];"
          f"[bg][a]overlay={xl}:{y}[t1];[t1][b]overlay={xr}:{y}[t2];"
          f"[t2][2:v]overlay=0:0,{fades(d)}[o]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(left), "-i", str(right), "-i", str(lab),
         "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def pan(name: str, png: Path, d: float, label: Path | None) -> Path:
    """A wide figure drifting sideways at a constant speed (crop on an upscaled frame; no zoom, so no jitter)."""
    out = SEG / f"{name}.mp4"
    H = 940 if label else 1080
    W2 = 2160                                   # 240 px of travel over the whole shot
    vf = (f"[0:v]scale=1920:{H}:force_original_aspect_ratio=decrease,pad=1920:{H}:(ow-iw)/2:(oh-ih)/2:black,"
          f"scale={W2}:-2:flags=lanczos,fps={FPS},crop=1920:{H}:x='({W2}-1920)*t/{d:.2f}':y='(ih-{H})/2',pad=1920:1080:0:8:black")
    if label:
        fc = f"{vf}[v];[v][1:v]overlay=0:0,{fades(d)}[o]"
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(png), "-i", str(label), "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(png), "-filter_complex", f"{vf},{fades(d)}[o]", "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def split(name: str, a: Path, b: Path, d: float, label: Path) -> Path:
    """Before | after, side by side, with small BEFORE / AFTER tags."""
    out = SEG / f"{name}.mp4"
    w = 900
    h = int(800 * w / 1280)
    y = 230
    fc = (f"color=c=black:s=1920x1080:r={FPS}:d={d:.2f}[bg];[0:v]scale={w}:{h}[a];[1:v]scale={w}:{h}[b];"
          f"[bg][a]overlay=40:{y}[t1];[t1][b]overlay={1920 - 40 - w}:{y}[t2];"
          f"[t2]drawbox=x={1920 - 40 - w}:y={y}:w={w}:h={h}:color=0xC0504D@1:t=4[t3];[t3][2:v]overlay=0:0,{fades(d)}[o]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(a), "-loop", "1", "-i", str(b), "-i", str(label),
         "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def main() -> None:
    img, vid = ROOT / "docs" / "img", ROOT / "docs" / "video"
    GLASSES = vid / "glasses-pov.mp4" if (vid / "glasses-pov.mp4").exists() else vid / "glasses.mp4"
    GLASSES_SPEED = 1.0 if GLASSES.name == "glasses-pov.mp4" else 1.7
    C = lambda n: CARDS / f"{n}.png"  # noqa: E731
    # (segment builder, narration)
    plan = [
        ("s01_title", lambda d: card("s01_title", C("title"), d), "This is NeuroMuse. The Muse with a cortex.", 8.0),
        ("s02_problem", lambda d: card("s02_problem", C("problem"), d),
         "Ask any assistant what it thinks of your photo. It says: looks great. It never looked, and it can't say why.", 6.0),
        ("s03_idea", lambda d: card("s03_idea", C("idea"), d),
         "So we gave it a cortex. Meta's TRIBE v2 predicts how a human brain responds, every second. Muse Spark speaks only from that.", 6.0),
        ("s05_glasses", lambda d: left("s05_glasses", GLASSES, d, C("pn_glasses"), speed=GLASSES_SPEED),
         "Point your glasses at anything and ask. The clip goes through a predicted human cortex. Here it says the room's layout dominates, and desirability is at the bottom, with ninety three percent confidence. Where the signal is faint, it does not pretend.", 15.0),
        ("s06_scenes", lambda d: card("s06_scenes", C("scenes"), d),
         "Here is exactly what it says about six everyday scenes, from a live run. Mostly, the room's layout dominates and desirability is low. Where its confidence is under point three, it says the signal is faint and asks you instead of guessing.", 14.0),
        ("s07_phones", lambda d: phones("s07_phones", vid / "chat.mp4", vid / "lab.mp4", d, 3.3, 1.7, C("pn_phones")),
         "The cortex plays first, then the heads score it. Every like is stored as a brain state, not as words, so recall means: what felt like this. And every score names the cortical areas behind it.", 14.0),
        ("s08_tune", lambda d: left("s08_tune", vid / "lab.mp4", d, C("pn_tune"), speed=1.0),
         "And it tunes to your brain. Every like or dislike is stored with its cortex state. While it sleeps, it replays what it got wrong, refits a personal head, and writes your taste as rules with effect sizes. At twelve answers it is not yet better than the crowd, and it tells you so.", 18.0),
        ("s085_viral", lambda d: left("s085_viral", img / "ad-timecourse.png", d, C("pn_viral"), still=True),
         "What will spread? Attention is trained on watch retention, so it shows the second a viewer is lost. Reach is barely predictable from any features, cortex or raw, and we say that too.", 13.0),
        ("s09_room", lambda d: left("s09_room", ROOT / "results/showcase/studio/living5/timelapse.gif", d, C("pn_room"), speed=1.4),
         "It also directs the work. It reads each Blender render, says what it felt, and the agent edits the room. Brain score from point three two to point four nine, and a designer judge agrees.", 12.0),
        ("s11_site", lambda d: card("s11_site", C("sites"), d),
         "On real websites it evolves instead of replacing, behind three gates: no invented facts, density kept, and a blind judge. Of six real sites it changed one, at point nine zero, and refused five. People preferred its work eleven times out of sixteen.", 14.0),
        ("s12_ad", lambda d: left("s12_ad", img / "trail-ad.png", d, C("pn_ad"), still=True),
         "And it goes all the way to an ad, second by second. Only a brain model sees when attention peaks and fades. It won three of three clips. On the serum ad the one shot still won, and the trail says so.", 13.0),
        ("s125_text", lambda d: left("s125_text", img / "text-support.png", d, C("pn_text"), still=True),
         "Writing goes through the same brain. A chatbot's support reply, rewritten with the reader's cortex as critic: the blind judge prefers the rewrite, at point nine zero.", 11.0),
        ("s13_grid", lambda d: card("s13_grid", C("grid"), d), "One brain, many tasks: real websites, 3D rooms, ads, and the everyday scenes you look at.", 7.5),
        ("s14_arch", lambda d: card("s14_arch", C("arch"), d),
         "Here is the whole system. Glasses clips, photos, text and audio pass through Meta's open encoders into TRIBE v2, which predicts the cortex. Our calibrated heads score it, engram memory keeps it as a brain state, and Muse Spark speaks only from those outputs. And the same score that judges also steers: every render goes back in.", 12.0),
        ("s15_layers", lambda d: card("s15_layers", C("layers"), d), "Underneath, six layers. Only one holds memory, only one writes it, and the voice holds none.", 7.0),
        ("s16_numbers", lambda d: card("s16_numbers", C("numbers"), d),
         "Why a cortex? On twenty five hundred rated photos, cortical areas match the raw embedding's accuracy, and every score comes with its reasons. Every number here is measured, including the losses.", 11.0),
        ("s17_close", lambda d: card("s17_close", C("close"), d), "NeuroMuse. An opinion it can justify.", 9.0),
    ]
    segs, audio, t = [], [], 0.0
    for name, build, text, min_d in plan:
        wav, vd = vo(name, text)
        d = max(min_d * 0.6, vd + 0.4)
        print(f"{name}: {d:.1f}s (voice {vd:.1f}s)", flush=True)
        segs.append(build(d))
        if wav:
            audio.append((wav, t + 0.3))
        t += d
    total = t
    lst = SEG / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in segs))
    video = SEG / "video.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    # narration on a quiet pad (A major, slow swell), ducked under the voice
    pad = SEG / "pad.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"aevalsrc='0.06*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*0.07*t))+0.045*sin(2*PI*164.81*t)*(0.6+0.4*sin(2*PI*0.05*t+1))"
         f"+0.035*sin(2*PI*277.18*t)*(0.5+0.5*sin(2*PI*0.04*t+2))+0.02*sin(2*PI*329.63*t)':s=48000:d={total:.2f}",
         "-af", f"lowpass=f=900,afade=t=in:d=2.5,afade=t=out:st={total - 3:.2f}:d=3,volume=0.55", "-ac", "2", str(pad)])
    ins = ["-i", str(pad)]
    parts = []
    for i, (wav, start) in enumerate(audio, start=1):
        ins += ["-i", str(wav)]
        ms = int(start * 1000)
        parts.append(f"[{i}:a]adelay={ms}|{ms},volume=1.25[v{i}]")
    vmix = "".join(f"[v{i}]" for i in range(1, len(audio) + 1))
    fc = ";".join(parts) + f";{vmix}amix=inputs={len(audio)}:normalize=0[voice];[voice]asplit[vo1][vo2];" \
         f"[0:a][vo1]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[duck];[duck][vo2]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
    mix = SEG / "mix.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", fc, "-map", "[a]", "-t", f"{total:.2f}", str(mix)])
    out = ROOT / "docs" / "video" / "neuromuse-demo.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(mix), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(out)])
    print(f"done: {out} · {dur(out):.1f}s")


if __name__ == "__main__":
    main()

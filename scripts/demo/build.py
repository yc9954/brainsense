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


def vo(name: str, text: str) -> tuple[Path | None, float]:
    if not text:
        return None, 0.0
    aiff, wav = SEG / f"{name}.aiff", SEG / f"{name}.wav"
    subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(aiff), text], check=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(wav)])
    return wav, dur(wav)


ENC = ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-an"]


def fades(d: float) -> str:
    return f"fade=t=in:st=0:d={FADE},fade=t=out:st={d - FADE:.2f}:d={FADE}"


def card(name: str, png: Path, d: float, zoom: bool = True) -> Path:
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


def phones(name: str, left: Path, right: Path, d: float, lspeed: float, rspeed: float, lab: Path) -> Path:
    """Two phone recordings side by side on black, each with a small caption above."""
    out = SEG / f"{name}.mp4"
    h = 900
    w = int(430 * h / 860)
    h = 890
    xl, xr = 1920 // 2 - w - 70, 1920 // 2 + 70
    y = 150
    fc = (f"color=c=black:s=1920x1080:r={FPS}:d={d:.2f}[bg];"
          f"[0:v]setpts=PTS/{lspeed},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:0:0,tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}[a];"
          f"[1:v]setpts=PTS/{rspeed},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:0:0,tpad=stop_mode=clone:stop_duration=60,trim=duration={d:.2f}[b];"
          f"[bg][a]overlay={xl}:{y}[t1];[t1][b]overlay={xr}:{y}[t2];"
          f"[2:v]scale=1920:1080[l1];[t2][l1]overlay=0:0,{fades(d)}[o]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(left), "-i", str(right), "-i", str(lab),
         "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    return out


def pan(name: str, png: Path, d: float, label: Path | None) -> Path:
    """A wide figure eased across the frame: fit to height, slow push and drift."""
    out = SEG / f"{name}.mp4"
    n = int(d * FPS)
    H = 940 if label else 1080
    vf = (f"[0:v]scale=1920:{H}:force_original_aspect_ratio=decrease,pad=1920:{H}:(ow-iw)/2:(oh-ih)/2:black,scale=2400:-2,"
          f"zoompan=z='1.0+0.06*on/{n}':x='(iw-iw/zoom)*on/{n}':y='(ih-ih/zoom)/2':d={n}:s=1920x{H}:fps={FPS},pad=1920:1080:0:8:black")
    if label:
        fc = f"{vf}[v];[v][1:v]overlay=0:0,{fades(d)}[o]"
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(label), "-filter_complex", fc, "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-filter_complex", f"{vf},{fades(d)}[o]", "-map", "[o]", "-t", f"{d:.2f}", *ENC, str(out)])
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
    C = lambda n: CARDS / f"{n}.png"  # noqa: E731
    # (segment builder, narration)
    plan = [
        ("s01_title", lambda d: card("s01_title", C("title"), d), "This is NeuroMuse. The Muse with a cortex.", 4.0),
        ("s02_problem", lambda d: card("s02_problem", C("problem"), d),
         "Ask any assistant what it thinks of your photo. It says: looks great. It never looked, and it can't say why.", 6.0),
        ("s03_idea", lambda d: card("s03_idea", C("idea"), d),
         "So we gave it a cortex. Meta's TRIBE v2 predicts how a human brain responds, every second. Muse Spark speaks only from that.", 6.0),
        ("s04_sec", lambda d: card("s04_sec", C("sec_glasses"), d, zoom=False), "", 1.4),
        ("s05_glasses", lambda d: clip("s05_glasses", vid / "glasses.mp4", d, C("lb_glasses"), speed=1.9),
         "Point your glasses at anything and ask. The brain answers in its own words: what fired, how strongly, and what stayed faint.", 12.0),
        ("s06_sec", lambda d: card("s06_sec", C("sec_lab"), d, zoom=False), "", 1.4),
        ("s07_phones", lambda d: phones("s07_phones", vid / "chat.mp4", vid / "lab.mp4", d, 3.3, 1.7, C("lb_phones")),
         "The cortex lights up first, then five calibrated heads score it, each with a confidence. Every like is stored as a brain state, and your taste model refits on the spot.", 12.0),
        ("s08_sec", lambda d: card("s08_sec", C("sec_loop"), d, zoom=False), "", 1.4),
        ("s09_room", lambda d: clip("s09_room", ROOT / "results/showcase/studio/living5/timelapse.gif", d, C("lb_trail"), speed=1.7),
         "It also directs the work. It looks at a render, says what it felt, and the agent changes the room in Blender.", 8.0),
        ("s10_trail", lambda d: pan("s10_trail", img / "trail-living5.png", d, None), "Every step is logged in the brain's own words.", 4.5),
        ("s11_site", lambda d: split("s11_site", img / "algonauts-before.png", img / "algonauts-after.png", d, C("lb_algo")),
         "On real websites it evolves instead of replacing. Facts are checked, and a blind judge decides. Of six real sites, it changed one and refused the rest.", 8.0),
        ("s12_ad", lambda d: pan("s12_ad", img / "trail-ad.png", d, C("lb_ad")),
         "It goes all the way to a twelve-second ad, with the product modelled in 3D. When its version loses, it says so.", 7.0),
        ("s13_grid", lambda d: card("s13_grid", C("grid"), d), "One brain, many tasks: real websites, 3D rooms, ads, and the everyday scenes you look at.", 7.5),
        ("s14_sec", lambda d: card("s14_sec", C("sec_memory"), d, zoom=False), "", 1.4),
        ("s15_layers", lambda d: card("s15_layers", C("layers"), d), "Underneath, it remembers in brain states, not words. Recall means: what have I seen that felt like this.", 7.0),
        ("s16_numbers", lambda d: card("s16_numbers", C("numbers"), d), "Every number is measured. Including the losses.", 5.5),
        ("s17_close", lambda d: card("s17_close", C("close"), d), "NeuroMuse. An opinion it can justify.", 5.0),
    ]
    segs, audio, t = [], [], 0.0
    for name, build, text, min_d in plan:
        wav, vd = vo(name, text)
        d = max(min_d, vd + 0.8)
        print(f"{name}: {d:.1f}s (voice {vd:.1f}s)", flush=True)
        segs.append(build(d))
        if wav:
            audio.append((wav, t + 0.45))
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
        parts.append(f"[{i}:a]adelay={ms}|{ms},volume=1.6[v{i}]")
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

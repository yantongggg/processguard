from __future__ import annotations

import json
import subprocess
from pathlib import Path

import torch
import torchaudio
import chatterbox.tts as cbtts


class NoWatermarker:
    def apply_watermark(self, wav, sample_rate):
        return wav


cbtts.perth.PerthImplicitWatermarker = NoWatermarker
ChatterboxTTS = cbtts.ChatterboxTTS

BASE = Path(__file__).resolve().parent
OUT = BASE / "out" / "movie_voice"
REFERENCE = BASE / "out" / "voice" / "reference_clean.wav"
CKPT = BASE / "out" / "voice" / "chatterbox_ckpt"
CHUNKS_DIR = OUT / "chunks"
SFX_DIR = OUT / "sfx"
CONCAT_FILE = OUT / "concat.txt"
MANIFEST = OUT / "manifest.json"
VO_RAW = OUT / "movie_vo_raw.wav"
VO_PADDED = OUT / "movie_vo_padded.wav"
SFX_TRACK = OUT / "movie_sfx.wav"
FINAL_MIX = OUT / "movie_voiceover_mix.wav"

TIMELINE_SECONDS = [
    0.6, 10.2, 21.0, 35.2,
    45.5, 60.0, 70.0, 84.0,
    90.5, 109.0, 124.0, 140.0,
    150.4, 174.0, 190.0,
    210.3, 226.0, 239.0, 254.0,
    270.5,
]

CHUNKS = [
    "In the race to deploy AI agents, enterprises are sitting on a time bomb.",
    "Agents are eager to please. But sometimes, pleasing the customer means breaking the law.",
    "No human oversight. No audit trail. Just a hallucinated shortcut.",
    "It is time to stop the chaos. Meet ProcessGuard.",
    "This is not just an observability tool. It is a runtime firewall that enforces your business process management.",
    "We use ISO standard B P M N diagrams as executable policy rules.",
    "No complex coding. If you can draw the flow, you can enforce it.",
    "Let us see it in action.",
    "Our agent is processing a refund for a V I P customer. It sees the money, and it sees a shortcut.",
    "Watch closely. The agent is about to bypass the manager approval step.",
    "In production, this is a compliance violation.",
    "This is where most tools would just log an error. But we do something different.",
    "Blocked. The A P I call is intercepted mid flight. The damage is stopped at zero.",
    "Our L L M judge analyzes the policy and generates a corrective path.",
    "The agent accepts the guidance, corrects its course, and completes the process legally.",
    "Every decision is recorded. Allowed calls. Blocked violations. Warnings. Judge verdicts.",
    "All of it becomes audit evidence.",
    "Fully compliant with E U AI Act Article fourteen. Human oversight is built in, not bolted on.",
    "Built to integrate with UiPath Automation Cloud. Drop it in as middleware. No agent rewrite needed.",
    "ProcessGuard. Do not just observe AI. Control it.",
]


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def ffmpeg(args: list[str]) -> None:
    run(["ffmpeg", "-y", *args])


def make_sfx() -> None:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=1800:duration=0.035",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=0.33",
        "-filter_complex", "[0:a]volume=0.12[a0];[a0][1:a]concat=n=2:v=0:a=1,atrim=0:0.36",
        "-ar", "48000", "-ac", "1", str(SFX_DIR / "tick.wav"),
    ])
    ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=95:duration=0.7",
        "-f", "lavfi", "-i", "sine=frequency=120:duration=0.7",
        "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.32,afade=t=out:st=0.5:d=0.2",
        "-ar", "48000", "-ac", "1", str(SFX_DIR / "bass.wav"),
    ])
    ffmpeg([
        "-f", "lavfi", "-i", "anoisesrc=color=white:duration=0.42:sample_rate=48000",
        "-filter_complex", "highpass=f=1200,lowpass=f=4800,volume=0.12,afade=t=out:st=0.30:d=0.12",
        "-ar", "48000", "-ac", "1", str(SFX_DIR / "glitch.wav"),
    ])
    ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=155:duration=0.68",
        "-f", "lavfi", "-i", "sine=frequency=77:duration=0.68",
        "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.45,afade=t=out:st=0.45:d=0.23",
        "-ar", "48000", "-ac", "1", str(SFX_DIR / "clang.wav"),
    ])
    ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=880:duration=0.18",
        "-f", "lavfi", "-i", "sine=frequency=1320:duration=0.24",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1,volume=0.18,afade=t=out:st=0.28:d=0.12",
        "-ar", "48000", "-ac", "1", str(SFX_DIR / "ding.wav"),
    ])


def mix_sfx() -> None:
    make_sfx()
    ffmpeg([
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=299.45",
        "-stream_loop", "-1", "-i", str(SFX_DIR / "tick.wav"),
        "-i", str(SFX_DIR / "glitch.wav"),
        "-i", str(SFX_DIR / "clang.wav"),
        "-i", str(SFX_DIR / "ding.wav"),
        "-i", str(SFX_DIR / "bass.wav"),
        "-filter_complex",
        (
            "[1:a]atrim=0:9.8,volume=0.38[tick];"
            "[2:a]adelay=20000|20000,volume=0.65[glitch];"
            "[3:a]adelay=150000|150000,volume=0.85[clang];"
            "[4:a]adelay=190000|190000,volume=0.65[ding];"
            "[5:a]adelay=270000|270000,volume=0.70[bass];"
            "[0:a][tick][glitch][clang][ding][bass]amix=inputs=6:duration=first:dropout_transition=0,volume=0.85"
        ),
        "-ar", "48000", "-ac", "1", str(SFX_TRACK),
    ])


def mix_timecoded_voiceover() -> None:
    chunk_paths = [CHUNKS_DIR / f"chunk_{index:03d}.wav" for index in range(1, len(CHUNKS) + 1)]
    missing = [str(path) for path in chunk_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing generated chunks: " + ", ".join(missing))

    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=299.45"]
    for path in chunk_paths:
        args.extend(["-i", str(path)])
    args.extend(["-i", str(SFX_TRACK)])

    filters = []
    mix_inputs = ["[0:a]"]
    for index, start in enumerate(TIMELINE_SECONDS, 1):
        delay = int(round(start * 1000))
        filters.append(f"[{index}:a]adelay={delay}|{delay},volume=1.0[v{index}]")
        mix_inputs.append(f"[v{index}]")
    sfx_input = len(chunk_paths) + 1
    filters.append(f"[{sfx_input}:a]volume=0.68[sfx]")
    mix_inputs.append("[sfx]")
    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0,"
        + "loudnorm=I=-16:LRA=11:TP=-1.5,atrim=0:299.45[out]"
    )
    args.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "48000", "-ac", "1", str(FINAL_MIX)])
    run(args)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    for old in CHUNKS_DIR.glob("chunk_*.wav"):
        old.unlink()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Loading Chatterbox from local checkpoint on {device}...", flush=True)
    model = ChatterboxTTS.from_local(CKPT, device)
    model.prepare_conditionals(str(REFERENCE), exaggeration=0.55)

    rows = []
    print(f"Generating {len(CHUNKS)} movie VO chunks...", flush=True)
    for index, text in enumerate(CHUNKS, 1):
        out = CHUNKS_DIR / f"chunk_{index:03d}.wav"
        print(f"[{index:02d}/{len(CHUNKS)}] {text[:84]}", flush=True)
        wav = model.generate(
            text,
            exaggeration=0.55,
            cfg_weight=0.45,
            temperature=0.70,
            repetition_penalty=1.18,
        )
        torchaudio.save(str(out), wav, model.sr)
        rows.append({"index": index, "text": text, "path": str(out)})

    MANIFEST.write_text(json.dumps(rows, indent=2))
    CONCAT_FILE.write_text("".join(f"file '{Path(row['path']).resolve()}'\n" for row in rows))
    mix_sfx()
    mix_timecoded_voiceover()
    print(FINAL_MIX, flush=True)


if __name__ == "__main__":
    main()
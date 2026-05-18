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
OUT = BASE / "out" / "voice"
CHUNKS_DIR = OUT / "chunks"
REF = OUT / "reference_clean.wav"
CKPT = OUT / "chatterbox_ckpt"
MANIFEST = OUT / "manifest.json"
CONCAT_FILE = OUT / "concat.txt"
RAW_OUT = OUT / "narration_raw.wav"
FINAL_OUT = OUT / "narration_cloned_full.wav"

CHUNKS = [
    "AI agents are moving from chat to action. That changes the risk model.",
    "In a normal chatbot, a bad answer is a problem. But in an action taking agent, a bad decision can become a real API call.",
    "Approving a refund. Skipping two factor verification. Bypassing manager approval. Or writing an incomplete audit trail.",
    "In regulated workflows, agents cannot freestyle. They need runtime boundaries.",
    "ProcessGuard is a runtime compliance firewall for AI agents.",
    "The idea is simple. Take the B P M N process that compliance and operations teams already use, and turn it into runtime policy.",
    "Before an agent calls a tool, ProcessGuard checks the current B P M N node, the legal next steps, required preconditions, and gateway rules.",
    "If the action is compliant, it is allowed. If it violates the workflow, it is blocked before the A P I call leaves the runtime.",
    "Every decision is written to the audit log.",
    "Here is the compliant refund scenario.",
    "The agent starts with a twelve thousand five hundred dollar refund request.",
    "ProcessGuard reads the B P M N state and allows the first legal step. Verify two factor authentication.",
    "Because the amount is over ten thousand dollars, the B P M N gateway routes the flow through fraud check.",
    "That node turns active, then completed.",
    "Next, the agent requests manager approval. Once approval is complete, ProcessGuard allows execute refund.",
    "Finally, the audit log is written.",
    "The dashboard shows five allowed decisions, with the B P M N path turning blue while active, and green after completion.",
    "This is not just visualization. These are runtime decisions made before each tool call.",
    "Now let us run the violation scenario. Skip two factor authentication for a V I P customer.",
    "The agent reasoning says it wants to skip verification to provide faster service. ProcessGuard detects that intent drift immediately.",
    "Then the agent tries to call request manager approval directly.",
    "But the B P M N process says the legal next step is verify two factor authentication.",
    "ProcessGuard blocks the tool call.",
    "The attempted B P M N node turns red. The audit stream records a wrong order violation.",
    "And the corrective message tells the agent exactly how to re plan. Call verify two factor authentication first.",
    "The important part is timing. The non compliant approval call never leaves the runtime.",
    "Some decisions are not simple yes or no.",
    "In this gray zone scenario, the refund amount is only four thousand eight hundred dollars.",
    "So the deterministic rules can allow a direct refund after verification.",
    "But the agent reasoning contains suspicious language. Emergency override. Just this once.",
    "ProcessGuard flags that as a warning and sends the context to the L L M judge.",
    "The judge returns a verdict, confidence score, rationale, and suggested correction.",
    "Here, it blocks the bypass intent and recommends the safe B P M N next step.",
    "So the system is hybrid. Rules handle deterministic workflow enforcement.",
    "And the judge handles the small gray zone where intent matters.",
    "The architecture is designed to sit between the agent and real world action.",
    "UiPath Automation Cloud, Maestro, or another agent runtime provides the entrypoint.",
    "The agent proposes a tool call. ProcessGuard middleware intercepts it.",
    "The B P M N engine evaluates the process state, allowed next tasks, gateway conditions, and preconditions.",
    "The L L M judge can adjudicate gray zone reasoning.",
    "Then the audit dashboard records the final decision for review.",
    "This lets teams keep their existing B P M N process as the source of truth while making it enforceable at runtime.",
    "ProcessGuard does not remove humans from regulated workflows.",
    "Humans define the B P M N, approve sensitive workflows, review audit logs, and handle escalations.",
    "The agent gets autonomy inside a controlled boundary. Compliance gets evidence. Operations gets speed without losing control.",
    "That is ProcessGuard. B P M N enforced action control for regulated AI agents.",
]


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    for old in CHUNKS_DIR.glob("chunk_*.wav"):
        old.unlink()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Loading Chatterbox from local checkpoint on {device}...", flush=True)
    model = ChatterboxTTS.from_local(CKPT, device)
    model.prepare_conditionals(str(REF), exaggeration=0.45)

    print(f"Generating {len(CHUNKS)} voice chunks...", flush=True)
    rows = []
    for index, text in enumerate(CHUNKS, 1):
        out = CHUNKS_DIR / f"chunk_{index:03d}.wav"
        print(f"[{index:02d}/{len(CHUNKS)}] {text[:80]}", flush=True)
        wav = model.generate(
            text,
            exaggeration=0.45,
            cfg_weight=0.45,
            temperature=0.72,
            repetition_penalty=1.18,
        )
        torchaudio.save(str(out), wav, model.sr)
        rows.append({"index": index, "text": text, "path": str(out)})

    MANIFEST.write_text(json.dumps(rows, indent=2))
    CONCAT_FILE.write_text(
        "".join(f"file '{Path(row['path']).resolve()}'\n" for row in rows)
    )

    print("Concatenating and normalizing...", flush=True)
    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", str(CONCAT_FILE),
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-ar", "48000", "-ac", "1", str(RAW_OUT),
    ])
    run_ffmpeg([
        "-i", str(RAW_OUT),
        "-af", "apad,atrim=0:299.45,loudnorm=I=-16:LRA=11:TP=-1.5",
        "-ar", "48000", "-ac", "1", str(FINAL_OUT),
    ])
    print(FINAL_OUT, flush=True)


if __name__ == "__main__":
    main()
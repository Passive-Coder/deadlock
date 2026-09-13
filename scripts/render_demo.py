"""Render a labeled recorded-evidence walkthrough, without fabricating UI footage.

Run after scripts/evaluate.py --live --trials 5. Requires Pillow and ffmpeg.
The timeline uses captured backend states at their recorded wall-clock times.
"""

import argparse
import bisect
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

BG = "#111410"
INK = "#F2F3ED"
MUTED = "#A1A99C"
LIME = "#C2EE87"
AMBER = "#E4B975"
LINE = "#354030"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="docs/evaluation.json")
    parser.add_argument("--output", default="docs/DEADLOCK-demo.mp4")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text())
    canonical = next(
        t
        for t in report["trials"]
        if t["scenario"] == "canonical" and t["strategy"] == "live" and t["validated"]
    )
    stale = next(t for t in report["trials"] if t["scenario"] == "stale_plan" and t["strategy"] == "live")
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font_path = next((f for f in font_paths if Path(f).exists()), None)
    if not font_path:
        raise SystemExit("Install Arial or DejaVu Sans to render the walkthrough")
    fonts = {s: ImageFont.truetype(font_path, s) for s in [14, 17, 20, 23, 28, 36, 46]}
    frames_dir = Path(".deadlock/demo-render")
    frames_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path("docs/demo-evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def base(title, subtitle):
        im = Image.new("RGB", (1280, 720), BG)
        d = ImageDraw.Draw(im)
        d.text((48, 28), "DEADLOCK / RECORDED EVIDENCE WALKTHROUGH", font=fonts[17], fill=LIME)
        d.text((48, 74), title, font=fonts[36], fill=INK)
        d.text((48, 128), subtitle, font=fonts[20], fill=MUTED)
        d.line((48, 670, 1232, 670), fill=LINE)
        d.text(
            (48, 686),
            "Recorded backend states • Real model calls • Reconstructed visualization, not browser footage",
            font=fonts[14],
            fill=MUTED,
        )
        return im, d

    def arrow(d, a, b, color):
        d.line((a, b), fill=color, width=2)
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        pts = [
            b,
            (b[0] - 10 * math.cos(angle - 0.4), b[1] - 10 * math.sin(angle - 0.4)),
            (b[0] - 10 * math.cos(angle + 0.4), b[1] - 10 * math.sin(angle + 0.4)),
        ]
        d.polygon(pts, fill=color)

    def state_frame(state, trial, origin, offset):
        elapsed = offset - origin
        im, d = base(
            "A circular wait. An evidence-backed recovery.",
            f"{trial['scenario']}  /  {trial['engine']}  /  seed {trial['seed']}  /  recorded t+{elapsed:.1f}s",
        )
        xs = {"A": 180, "B": 480, "C": 780}
        rxs = {"r0": 180, "r1": 480, "r2": 780}
        for resource in state["resources"]:
            if resource["owner"] in xs:
                arrow(d, (rxs[resource["id"]], 370), (xs[resource["owner"]], 260), LIME)
        for worker in state["workers"]:
            if worker["waiting"] in rxs:
                arrow(d, (xs[worker["id"]] + 22, 260), (rxs[worker["waiting"]] + 22, 370), AMBER)
        for w in state["workers"]:
            x = xs[w["id"]]
            d.rounded_rectangle((x - 120, 182, x + 120, 266), radius=8, fill="#20291B", outline=LINE, width=2)
            d.text((x - 100, 193), w["name"], font=fonts[23], fill=INK)
            d.text(
                (x - 100, 230), w["state"], font=fonts[17], fill=LIME if w["state"] == "COMPLETED" else MUTED
            )
            d.text((x - 116, 460), f"{w['progress']}/{w['total']} processed", font=fonts[20], fill=INK)
            d.rectangle((x - 116, 496, x + 116, 502), fill=LINE)
            d.rectangle((x - 116, 496, x - 116 + 232 * w["progress"] / w["total"], 502), fill=LIME)
            d.text((x - 116, 518), f"Checkpoint: {w['checkpoint_work']} units", font=fonts[17], fill=MUTED)
        for r in state["resources"]:
            x = rxs[r["id"]]
            d.rounded_rectangle((x - 120, 370, x + 120, 432), radius=6, fill="#182014", outline=LINE)
            d.text((x - 105, 380), r["name"], font=fonts[20], fill=INK)
            d.text(
                (x - 105, 407),
                "Held by " + r["owner"] if r["owner"] else "Available",
                font=fonts[14],
                fill=LIME,
            )
        d.line((947, 179, 947, 635), fill=LINE)
        inc = state["incident"] or {}
        d.text((980, 188), inc.get("status", "OBSERVING"), font=fonts[20], fill=LIME)
        d.text((980, 231), f"Plans {inc.get('attempts', 0)}/2", font=fonts[20], fill=INK)
        d.text((980, 269), f"Tool calls {inc.get('tool_calls', 0)}/8", font=fonts[20], fill=INK)
        plan = inc.get("plan")
        if plan:
            c = plan["candidate"]
            d.text((980, 326), "Selected: " + c["worker_id"], font=fonts[28], fill=INK)
            d.text((980, 373), f"Lost: {c['lost_work']} units", font=fonts[20], fill=AMBER)
            d.text((980, 410), f"Saved: {c['checkpoint_work']} units", font=fonts[20], fill=LIME)
        d.text((980, 493), f"{len(state['artifacts'])}/3 outputs", font=fonts[28], fill=INK)
        d.text((980, 535), "Content validated", font=fonts[17], fill=MUTED)
        if state.get("event"):
            msg = state["event"]["message"]
            d.text((48, 597), msg[:95], font=fonts[20], fill=INK)
        d.text(
            (48, 636),
            "Lime: lease ownership     Amber: blocking request     Workers are scripted; the mediator is live.",
            font=fonts[14],
            fill=MUTED,
        )
        return im

    intro, d = base(
        "Observe actual agents. Verify resource recovery.",
        "A local Codex/Claude dashboard plus an instrumented Exasol recovery lab.",
    )
    for y, title, body in [
        (222, "01  OBSERVE", "Real process-tree CPU, RSS memory, workspaces and open files."),
        (343, "02  CONTROL", "Launch or adopt standalone coding agents. Pause, resume, stop."),
        (464, "03  VERIFY", "Scripted lab workers. Live mediator. Actual CSV, HTML and ZIP outputs."),
    ]:
        d.text((64, y), title, font=fonts[28], fill=LIME)
        d.text((64, y + 51), body, font=fonts[23], fill=INK)
    segments = [(intro, 7)]
    manifest = {
        "report": args.report,
        "format": "recorded backend visualization; no browser footage",
        "runs": [],
    }
    for trial in [canonical, stale]:
        source = Path(".deadlock/evaluation/runs") / trial["run_id"]
        timeline = json.loads((source / "timeline.json").read_text())
        evidence = json.loads((source / "evaluation-evidence.json").read_text())
        for name in ["timeline.json", "evaluation-evidence.json"]:
            shutil.copyfile(source / name, evidence_dir / (trial["scenario"] + "-" + name))
        for a in evidence["artifacts"]:
            shutil.copyfile(source / a["filename"], evidence_dir / (trial["scenario"] + "-" + a["filename"]))
        start = timeline[0]["time"]
        end = timeline[-1]["time"]
        origin = start
        if trial is stale:
            rejections = [
                t["time"]
                for t in evidence["incident"]["trace"]
                if isinstance(t["result"], dict) and t["result"].get("rejected") == "STALE_PLAN"
            ]
            if rejections:
                start = max(origin, rejections[0] - 4)
            title, d = base(
                "A stale proposal cannot mutate the runner.",
                "Recorded excerpt: ownership changes, rejection, bounded re-inspection, and the actual outcome.",
            )
            d.text((64, 285), "Ownership/version checks precede every recovery.", font=fonts[28], fill=INK)
            d.text(
                (64, 359),
                "The same 2-proposal / 8-tool / 60-second budgets apply.",
                font=fonts[28],
                fill=LIME,
            )
            segments.append((title, 5))
        segments.append(
            (
                {"timeline": timeline, "trial": trial, "start": start, "end": end, "origin": origin},
                end - start + 1,
            )
        )
        manifest["runs"].append(
            {
                "run_id": trial["run_id"],
                "scenario": trial["scenario"],
                "start_offset": start - origin,
                "duration": end - start + 1,
                "status": trial["status"],
            }
        )
    outro, d = base(
        "Measured results and reproducible setup.",
        "github.com/Passive-Coder/deadlock  /  ./scripts/dev.sh  /  localhost:8765",
    )
    live = [t for t in report["trials"] if t["strategy"] == "live" and t["scenario"] == "canonical"]
    times = [t["recovery_seconds"] for t in live if t["validated"]]
    d.text(
        (64, 239),
        f"{sum(t['validated'] for t in live)}/{len(live)} canonical live trials validated",
        font=fonts[36],
        fill=LIME,
    )
    d.text(
        (64, 304),
        f"Recovery range: {min(times):.2f}–{max(times):.2f}s; see evaluation.json for every trial.",
        font=fonts[23],
        fill=INK,
    )
    d.text(
        (64, 392),
        "Real Codex lifecycle verified. Claude successful turn requires login.",
        font=fonts[23],
        fill=INK,
    )
    d.text(
        (64, 444),
        "Shared desktop runtimes are protected; per-task control needs a daemon socket.",
        font=fonts[23],
        fill=MUTED,
    )
    d.text(
        (64, 513),
        "No claims of arbitrary framework lock recovery or universal compatibility.",
        font=fonts[23],
        fill=MUTED,
    )
    segments.append((outro, 10))
    total = sum(duration for _, duration in segments)
    if total > 180:
        raise SystemExit(f"Walkthrough is {total:.1f}s; select a shorter, explicitly labeled excerpt")
    manifest["duration_seconds"] = total
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        "1280x720",
        "-r",
        "10",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        args.output,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frame_count = 0
    try:
        for segment, duration in segments:
            if isinstance(segment, dict):
                timeline = segment["timeline"]
                timestamps = [f["time"] for f in timeline]
            for n in range(math.ceil(duration * 10)):
                if isinstance(segment, dict):
                    t = min(segment["start"] + n / 10, segment["end"])
                    index = max(0, bisect.bisect_right(timestamps, t) - 1)
                    im = state_frame(timeline[index], segment["trial"], segment["origin"], t)
                else:
                    im = segment
                if n == 0:
                    im.save(frames_dir / f"frame-{frame_count}.png")
                proc.stdin.write(im.tobytes())
                frame_count += 1
        proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit("Video encoding failed")
    finally:
        if proc.poll() is None:
            proc.kill()
    print(json.dumps({"output": args.output, "seconds": frame_count / 10, "frames": frame_count}))


if __name__ == "__main__":
    main()

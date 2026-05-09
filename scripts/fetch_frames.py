#!/usr/bin/env python3
"""Descarga el mapa GFS para una fecha+hora objetivo desde múltiples runs del archivo
de meteociel y genera un manifest.json + log.txt."""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ARCHIVE_BASE = "https://modeles16.meteociel.fr/modeles/gfs/archives"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; gfs-evolution-bot/1.0)",
    "Referer": "https://www.meteociel.fr/",
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--target-hour", type=int, required=True, choices=[0, 6, 12, 18])
    p.add_argument("--days-back", type=int, default=10)
    p.add_argument("--map-param", default="gfs-0")
    p.add_argument("--out-dir", default="site/frames")
    p.add_argument("--manifest", default="site/frames/manifest.json")
    p.add_argument("--log", default="site/frames/log.txt")
    return p.parse_args()


def valid_fh(fh: int) -> bool:
    """GFS archive: paso 3h hasta 240h, paso 6h entre 240 y 384h."""
    if fh < 0 or fh > 384:
        return False
    if fh <= 240:
        return fh % 3 == 0
    return fh % 6 == 0


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_lines = []

    def log(msg):
        line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
        print(line)
        log_lines.append(line)

    y, m, d = map(int, args.target_date.split("-"))
    target = datetime(y, m, d, args.target_hour, tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    last_run_hour = (now.hour // 6) * 6
    last_run = now.replace(hour=last_run_hour, minute=0, second=0, microsecond=0)
    if (now - last_run) < timedelta(hours=2):
        last_run -= timedelta(hours=6)

    start_run = last_run - timedelta(days=args.days_back)

    log(f"Target: {target.isoformat()}")
    log(f"Range of runs: {start_run.isoformat()} -> {last_run.isoformat()}")
    log(f"Map param: {args.map_param}")

    candidates = []
    cur = start_run
    while cur <= last_run:
        fh = int((target - cur).total_seconds() // 3600)
        if valid_fh(fh):
            candidates.append((cur, fh))
        cur += timedelta(hours=6)

    log(f"Candidate frames: {len(candidates)}")

    session = requests.Session()
    session.headers.update(HEADERS)

    frames = []
    ok, fail = 0, 0
    for run_dt, fh in candidates:
        stamp = run_dt.strftime("%Y%m%d%H")
        url = f"{ARCHIVE_BASE}/{stamp}/{args.map_param}-{fh}.png"
        fname = f"{stamp}_fh{fh:03d}.png"
        fpath = out_dir / fname

        try:
            r = session.get(url, timeout=20)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "image" in ct and len(r.content) > 1000:
                fpath.write_bytes(r.content)
                frames.append({
                    "file": fname,
                    "run": run_dt.isoformat(),
                    "run_stamp": stamp,
                    "fh": fh,
                    "size": len(r.content),
                })
                ok += 1
                log(f"OK  {stamp} +{fh:>3}h  {len(r.content)//1024}KB  {url}")
            else:
                fail += 1
                log(f"SKIP {stamp} +{fh:>3}h  HTTP {r.status_code} ct={ct} len={len(r.content)}  {url}")
        except Exception as e:
            fail += 1
            log(f"ERR  {stamp} +{fh:>3}h  {type(e).__name__}: {e}  {url}")

        time.sleep(0.15)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target.isoformat(),
        "target_date": args.target_date,
        "target_hour": args.target_hour,
        "days_back": args.days_back,
        "map_param": args.map_param,
        "stats": {"ok": ok, "fail": fail, "total_candidates": len(candidates)},
        "frames": frames,
    }

    Path(args.manifest).write_text(json.dumps(manifest, indent=2))
    log(f"Done: {ok} OK, {fail} failed. Manifest: {args.manifest}")

    log_path.write_text("\n".join(log_lines) + "\n")

    if ok == 0:
        log("No frames downloaded - check log for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()

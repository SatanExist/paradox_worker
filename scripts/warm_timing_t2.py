#!/usr/bin/env python3
"""Back-to-back TRELLIS.2 jobs to compare cold vs warm handler timings (clay default)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from runpod_billing import estimate_from_status_payload  # noqa: E402
from runpod_queue_watchdog import (  # noqa: E402
    get_health,
    heal_endpoint,
    run_with_zombie_retries,
)

ENDPOINT = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "")
API_KEY = os.getenv("RUNPOD_API_KEY", "")

DEFAULT_IMAGE = (
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/"
    "typical_misc_monster_chest.png"
)


def job_input(
    *,
    pipeline: str,
    texture_mode: str,
    decimation: int,
    seed: int,
    image_url: str,
) -> dict:
    payload: dict = {
        "image_url": image_url,
        "pipeline_type": pipeline,
        "texture_mode": texture_mode,
        "seed": seed,
        "decimation_target": decimation,
        "return_base64": False,
    }
    return payload


def handler_ms(final: dict) -> dict:
    out = final.get("output") or {}
    billing = out.get("billing") or {}
    ms = billing.get("handler_ms") or {}
    return ms if isinstance(ms, dict) else {}


def summarize_row(
    idx: int,
    final: dict,
    wall_s: float,
    *,
    endpoint_id: str,
    api_key: str,
) -> dict:
    ms = handler_ms(final)
    est = estimate_from_status_payload(
        final,
        endpoint_id=endpoint_id,
        api_key=api_key,
    )
    load = int(ms.get("model_load_ms") or 0)
    total = int(ms.get("total_ms") or 0)
    infer = int(ms.get("inference_ms") or 0)
    export = int(ms.get("glb_export_ms") or 0)
    return {
        "job": idx,
        "status": final.get("status"),
        "wall_s": round(wall_s, 1),
        "delay_ms": final.get("delayTime"),
        "exec_ms": final.get("executionTime"),
        "load_s": round(load / 1000, 1),
        "infer_s": round(infer / 1000, 1),
        "export_s": round(export / 1000, 1),
        "handler_total_s": round(total / 1000, 1),
        "usd": est.get("cost_usd"),
    }


def print_table(rows: list[dict]) -> None:
    print("\n=== WARM TIMING TABLE ===")
    header = (
        f"{'#':>3}  {'status':<10}  {'wall_s':>7}  {'load_s':>6}  "
        f"{'infer_s':>7}  {'export_s':>7}  {'handler_s':>9}  {'usd':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        usd = r.get("usd")
        usd_s = f"{usd:.3f}" if isinstance(usd, (int, float)) else "n/a"
        print(
            f"{r['job']:>3}  {str(r['status']):<10}  {r['wall_s']:>7.1f}  "
            f"{r['load_s']:>6.1f}  {r['infer_s']:>7.1f}  {r['export_s']:>7.1f}  "
            f"{r['handler_total_s']:>9.1f}  {usd_s:>8}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="T2 warm timing (back-to-back jobs)")
    parser.add_argument("--count", type=int, default=5, help="Number of sequential jobs")
    parser.add_argument("--pipeline", default="512")
    parser.add_argument("--texture-mode", default="clay", choices=["clay", "textured"])
    parser.add_argument("--decimation", type=int, default=500_000)
    parser.add_argument("--image-url", default=DEFAULT_IMAGE)
    parser.add_argument("--zombie-after-s", type=float, default=180.0)
    parser.add_argument("--zombie-retries", type=int, default=2)
    parser.add_argument(
        "--no-zombie-watch",
        action="store_true",
        help="Wait without cancel/heal on idle+IN_QUEUE (better for warm back-to-back)",
    )
    parser.add_argument(
        "--no-heal",
        action="store_true",
        help="Skip ghost heal before each submit (keep workers warm)",
    )
    args = parser.parse_args()

    if not ENDPOINT or not API_KEY:
        raise SystemExit("Need RUNPOD_ENDPOINT_ID_TRELLIS2 and RUNPOD_API_KEY in .env")

    print("endpoint:", ENDPOINT)
    print("health before:", get_health(ENDPOINT, API_KEY))
    if not args.no_heal:
        heal_endpoint(ENDPOINT, API_KEY, purge=False, delete_ghosts=True)

    rows: list[dict] = []
    for i in range(1, args.count + 1):
        label = "cold/warmup" if i == 1 else "warm target"
        print(f"\n>>> JOB {i}/{args.count} ({label}): pipeline={args.pipeline} mode={args.texture_mode}")
        t0 = time.perf_counter()
        payload = job_input(
            pipeline=args.pipeline,
            texture_mode=args.texture_mode,
            decimation=args.decimation,
            seed=1,
            image_url=args.image_url,
        )
        if args.no_zombie_watch:
            from runpod_queue_watchdog import submit_job, wait_for_job

            job_id = submit_job(ENDPOINT, API_KEY, payload)
            final = wait_for_job(
                ENDPOINT,
                job_id,
                API_KEY,
                zombie_after_s=1e9,
                max_wait_s=30 * 60,
            )
        else:
            _, final = run_with_zombie_retries(
                ENDPOINT,
                API_KEY,
                payload,
                zombie_after_s=args.zombie_after_s,
                zombie_retries=args.zombie_retries,
                max_wait_s=30 * 60,
                heal=not args.no_heal,
            )
        wall = time.perf_counter() - t0
        row = summarize_row(
            i,
            final,
            wall,
            endpoint_id=ENDPOINT,
            api_key=API_KEY,
        )
        rows.append(row)
        print(
            f"JOB{i}: status={row['status']} wall_s={row['wall_s']} "
            f"load_s={row['load_s']} handler_s={row['handler_total_s']} usd={row['usd']}"
        )
        if final.get("status") != "COMPLETED":
            print_table(rows)
            return 1

    print_table(rows)

    warm_rows = [r for r in rows[1:] if r["status"] == "COMPLETED"]
    if warm_rows:
        avg_wall = sum(r["wall_s"] for r in warm_rows) / len(warm_rows)
        avg_load = sum(r["load_s"] for r in warm_rows) / len(warm_rows)
        avg_handler = sum(r["handler_total_s"] for r in warm_rows) / len(warm_rows)
        usd_vals = [r["usd"] for r in warm_rows if isinstance(r["usd"], (int, float))]
        avg_usd = sum(usd_vals) / len(usd_vals) if usd_vals else None
        print("\n=== WARM AVG (jobs 2..N) ===")
        print(f"wall_s={avg_wall:.1f} load_s={avg_load:.1f} handler_s={avg_handler:.1f} usd={avg_usd}")

    if rows:
        r1 = rows[0]
        print("\n=== COLD vs WARM hint ===")
        print(f"JOB1 wall_s={r1['wall_s']} load_s={r1['load_s']}")
        if warm_rows:
            print(f"JOB2+ avg wall_s={avg_wall:.1f} load_s={avg_load:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

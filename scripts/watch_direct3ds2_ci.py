"""Poll the build-direct3ds2 workflow until it finishes (needs GITHUB_TOKEN in .env)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

REPO = "SatanExist/paradox_worker"
WORKFLOW = "build-direct3ds2.yml"
POLL_SECONDS = 60


def main() -> int:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    once = "--once" in sys.argv

    while True:
        try:
            runs = requests.get(
                f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
                headers=headers,
                params={"per_page": 1},
                timeout=60,
            )
            runs.raise_for_status()
        except requests.RequestException as exc:
            print(f"poll failed, retrying: {exc}")
            if once:
                return 1
            time.sleep(POLL_SECONDS)
            continue
        items = runs.json().get("workflow_runs") or []
        if not items:
            print("no runs yet for build-direct3ds2")
            if once:
                return 0
            time.sleep(POLL_SECONDS)
            continue

        run = items[0]
        print(
            f"run {run['id']} {run['status']}/{run.get('conclusion')} "
            f"sha={run['head_sha'][:7]} {run['html_url']}"
        )

        if run["status"] == "completed":
            jobs = requests.get(
                f"https://api.github.com/repos/{REPO}/actions/runs/{run['id']}/jobs",
                headers=headers,
                timeout=60,
            ).json()
            for job in jobs.get("jobs", []):
                print(f"  job {job['name']}: {job['conclusion']}")
            return 0 if run.get("conclusion") == "success" else 1

        if once:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())

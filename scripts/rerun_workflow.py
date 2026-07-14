"""Re-run a failed GitHub Actions workflow run (requires GITHUB_TOKEN in .env)."""

from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

API = "https://api.github.com"
OWNER = "SatanExist"
REPO = "paradox_worker"


def get_token() -> str:
    load_dotenv()
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        print(
            "Set GITHUB_TOKEN (or GH_TOKEN) in .env with repo scope.\n"
            "Create: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained\n"
            "  Repository: paradox_worker, Permissions: Actions (read+write).",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def find_run_by_sha(token: str, sha: str) -> dict | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{API}/repos/{OWNER}/{REPO}/actions/runs"
    params = {"branch": "main", "per_page": 30}
    while url:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        for run in data.get("workflow_runs", []):
            if run.get("head_sha", "").startswith(sha):
                return run
        url = data.get("next_url") or (
            response.links.get("next", {}).get("url") if hasattr(response, "links") else None
        )
        params = None
    return None


def rerun(token: str, run_id: int) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{API}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/rerun"
    response = requests.post(url, headers=headers, timeout=60)
    response.raise_for_status()
    print(f"Re-run queued for workflow run {run_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-run a GitHub Actions workflow.")
    parser.add_argument(
        "--sha",
        default="e481ba4",
        help="Commit short/full SHA to find the workflow run (default: e481ba4).",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        help="Workflow run ID (skips SHA lookup). Example: 29275250294",
    )
    args = parser.parse_args()
    token = get_token()

    if args.run_id:
        run_id = args.run_id
        print(f"Using run id {run_id}")
    else:
        run = find_run_by_sha(token, args.sha)
        if not run:
            print(f"No workflow run found for sha {args.sha}", file=sys.stderr)
            return 1
        run_id = run["id"]
        print(
            f"Found run {run_id}: {run.get('display_title')} "
            f"({run.get('conclusion') or run.get('status')})"
        )

    rerun(token, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fetch last build-trellis2 job log (needs GITHUB_TOKEN in .env)."""
from __future__ import annotations

import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
if not token:
    sys.exit("No GITHUB_TOKEN")

headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
runs = requests.get(
    "https://api.github.com/repos/SatanExist/paradox_worker/actions/workflows/build-trellis2.yml/runs?per_page=1",
    headers=headers,
    timeout=30,
).json()["workflow_runs"]
run = runs[0]
print("run", run["id"], run["conclusion"], run["head_sha"][:7])
jobs = requests.get(
    f"https://api.github.com/repos/SatanExist/paradox_worker/actions/runs/{run['id']}/jobs",
    headers=headers,
    timeout=30,
).json()["jobs"]
job_id = jobs[0]["id"]
logs = requests.get(
    f"https://api.github.com/repos/SatanExist/paradox_worker/actions/jobs/{job_id}/logs",
    headers=headers,
    timeout=120,
).text
for line in logs.splitlines():
    if re.search(r"error|failed|fatal|==>|submodule|eigen|xformers|cumesh|flex|o_voxel|nvdiff", line, re.I):
        if "Node.js" not in line:
            print(line[:300])
print("\n--- TAIL ---")
print("\n".join(logs.splitlines()[-60:]))

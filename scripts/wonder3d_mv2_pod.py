"""MV2 Wonder3D: create RunPod pod, run oneshot (armor+chest), download views, terminate.

Uses public runpod/pytorch image (no GHCR). Always terminates pod in finally block.

Usage:
  python scripts/wonder3d_mv2_pod.py
  python scripts/wonder3d_mv2_pod.py --no-run   # create + print Web Terminal steps only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

REST = "https://rest.runpod.io/v1"
GQL = "https://api.runpod.io/graphql"
PUBLIC_IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
GPU_CANDIDATES = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA GeForce RTX 3090",
    "NVIDIA RTX A5000",
    "NVIDIA RTX A6000",
]
SSH_KEY = Path(os.getenv("RUNPOD_SSH_KEY", Path.home() / ".ssh" / "id_ed25519"))


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise SystemExit("RUNPOD_API_KEY missing in .env")
    return key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def create_pod(*, name: str, disk_gb: int) -> dict:
    body = {
        "name": name,
        "imageName": PUBLIC_IMAGE,
        "gpuTypeIds": GPU_CANDIDATES[:1],
        "gpuCount": 1,
        "containerDiskInGb": disk_gb,
        "volumeInGb": 20,
        "volumeMountPath": "/workspace",
        "ports": ["8888/http", "22/tcp"],
        "dockerStartCmd": ["sleep", "infinity"],
        "cloudType": "SECURE",
        "supportPublicIp": True,
    }
    last_err = ""
    for gpu in GPU_CANDIDATES:
        body["gpuTypeIds"] = [gpu]
        print(f"Creating pod gpu={gpu!r} image={PUBLIC_IMAGE!r} disk={disk_gb}G ...")
        r = requests.post(f"{REST}/pods", headers=_headers(), json=body, timeout=120)
        if r.status_code < 400:
            pod = r.json() if r.content else {}
            print(f"Created pod id={pod.get('id')}")
            return pod
        last_err = r.text[:800]
        print(f"  failed HTTP {r.status_code}: {last_err}")
    raise SystemExit(f"Pod create failed for all GPUs. Last: {last_err}")


def terminate_pod(pod_id: str) -> None:
    print(f"Terminating pod {pod_id} ...")
    r = requests.delete(f"{REST}/pods/{pod_id}", headers=_headers(), timeout=60)
    if r.status_code < 400:
        print("Terminate OK")
        return
    key = _api_key()
    mutation = """
    mutation($input: PodTerminateInput!) { podTerminate(input: $input) }
    """
    gr = requests.post(
        f"{GQL}?api_key={key}",
        json={"query": mutation, "variables": {"input": {"podId": pod_id}}},
        timeout=60,
    )
    print(f"Terminate GraphQL {gr.status_code}: {gr.text[:300]}")


def _pod_runtime_ports(pod_id: str) -> tuple[str, int] | None:
    key = _api_key()
    query = {
        "query": (
            "query ($id: String!) { pod(input: {podId: $id}) { id desiredStatus "
            "publicIp runtime { ports { ip publicPort privatePort type } } } }"
        ),
        "variables": {"id": pod_id},
    }
    gr = requests.post(f"{GQL}?api_key={key}", json=query, timeout=60)
    if not gr.ok:
        return None
    pod = (gr.json().get("data") or {}).get("pod") or {}
    ip = pod.get("publicIp")
    runtime = pod.get("runtime") or {}
    ports = runtime.get("ports") or []
    ssh_port = None
    for p in ports:
        if p.get("privatePort") == 22:
            ssh_port = int(p["publicPort"])
            ip = p.get("ip") or ip
            break
    if ip and ssh_port:
        return str(ip), ssh_port
    return None


def wait_ssh_ready(pod_id: str, *, timeout_s: int = 600) -> tuple[str, int]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{REST}/pods/{pod_id}", headers=_headers(), timeout=60)
        r.raise_for_status()
        d = r.json()
        status = d.get("desiredStatus")
        print(f"  status={status} publicIp={d.get('publicIp')!r}")
        rt = _pod_runtime_ports(pod_id)
        if rt and status == "RUNNING":
            return rt
        time.sleep(15)
    raise TimeoutError(f"Pod {pod_id} SSH not ready within {timeout_s}s")


def _ssh_cmd(ip: str, port: int, remote_cmd: str, *, timeout: int = 7200) -> int:
    if not SSH_KEY.is_file():
        print(f"SSH key missing: {SSH_KEY}", file=sys.stderr)
        return 2
    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=30",
        "-p",
        str(port),
        "-i",
        str(SSH_KEY),
        f"root@{ip}",
        remote_cmd,
    ]
    print("SSH:", " ".join(cmd[:8]), "...")
    return subprocess.call(cmd, timeout=timeout)


def _scp_file(ip: str, port: int, local: Path, remote: str) -> int:
    cmd = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-P",
        str(port),
        "-i",
        str(SSH_KEY),
        str(local),
        f"root@{ip}:{remote}",
    ]
    print("SCP:", " ".join(cmd))
    return subprocess.call(cmd, timeout=300)


def _scp_dir(ip: str, port: int, remote_glob: str, local_dir: Path) -> int:
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-P",
        str(port),
        "-i",
        str(SSH_KEY),
        f"root@{ip}:{remote_glob}",
        str(local_dir) + os.sep,
    ]
    print("SCP:", " ".join(cmd))
    return subprocess.call(cmd, timeout=600)


def build_upload_zip(zip_path: Path) -> Path:
    armor = ROOT / "preview_textures" / "ref_gold_armor.png"
    chest = ROOT / "preview_textures" / "ref_chest.png"
    infer = ROOT / "scripts" / "wonder3d_mv2_infer.py"
    oneshot = ROOT / "scripts" / "wonder3d_mv2_oneshot.sh"
    for p in (armor, chest, infer, oneshot):
        if not p.is_file():
            raise SystemExit(f"Missing upload file: {p}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(armor, "data/ref_gold_armor.png")
        zf.write(chest, "data/ref_chest.png")
        zf.write(infer, "scripts/wonder3d_mv2_infer.py")
        zf.write(oneshot, "scripts/wonder3d_mv2_oneshot.sh")
    print(f"Upload zip: {zip_path} ({zip_path.stat().st_size} bytes)")
    return zip_path


def main() -> int:
    p = argparse.ArgumentParser(description="MV2 Wonder3D pod automation")
    p.add_argument("--no-run", action="store_true", help="Create pod only; print manual steps")
    p.add_argument("--name", default="paradox-wonder3d-mv2")
    p.add_argument("--disk-gb", type=int, default=50)
    p.add_argument(
        "--keep",
        action="store_true",
        help="Do NOT terminate (dangerous — only for debug)",
    )
    args = p.parse_args()

    zip_local = ROOT / "mv2_upload.zip"
    build_upload_zip(zip_local)

    one_liner = (
        "cd /workspace && unzip -o /tmp/mv2_upload.zip -d /workspace "
        "&& sed -i 's/\\r$//' /workspace/scripts/wonder3d_mv2_oneshot.sh "
        "&& bash /workspace/scripts/wonder3d_mv2_oneshot.sh"
    )

    pod_id: str | None = None
    try:
        pod = create_pod(name=args.name, disk_gb=args.disk_gb)
        pod_id = str(pod.get("id") or "")
        if not pod_id:
            raise SystemExit(f"No pod id in response: {pod}")

        print("\nWeb Terminal (after zip at /tmp/mv2_upload.zip):")
        print(one_liner)
        print(
            "\nAfter DONE: download /workspace/outputs/mv2_* then "
            f"terminate {pod_id}"
        )

        if args.no_run:
            print(f"\nPod {pod_id} — manual mode; terminate yourself.")
            return 0

        print("\nWaiting for SSH ...")
        ip, port = wait_ssh_ready(pod_id)
        print(f"SSH ready root@{ip}:{port}")

        for attempt in range(12):
            rc = _ssh_cmd(ip, port, "echo SSH_OK", timeout=60)
            if rc == 0:
                break
            print(f"SSH attempt {attempt + 1} failed; retry in 20s")
            time.sleep(20)
        else:
            print("SSH failed — use Web Terminal one-liner above, then terminate.")
            return 1

        rc = _scp_file(ip, port, zip_local, "/tmp/mv2_upload.zip")
        if rc != 0:
            print("SCP zip failed", file=sys.stderr)
            return rc

        print("Running Wonder3D oneshot (HF download + infer; may take 15–40 min) ...")
        rc = _ssh_cmd(ip, port, one_liner, timeout=7200)
        if rc != 0:
            print(f"MV2 oneshot exit={rc}", file=sys.stderr)
            return rc

        armor_out = ROOT / "preview_textures" / "mv2_armor"
        chest_out = ROOT / "preview_textures" / "mv2_chest"
        _scp_dir(ip, port, "/workspace/outputs/mv2_armor/*", armor_out)
        _scp_dir(ip, port, "/workspace/outputs/mv2_chest/*", chest_out)
        print(f"Views saved under {armor_out} and {chest_out}")
        return 0
    finally:
        if pod_id and not args.keep:
            terminate_pod(pod_id)
        elif pod_id and args.keep:
            print(f"WARNING: --keep set; pod {pod_id} still RUNNING — terminate ASAP")


if __name__ == "__main__":
    raise SystemExit(main())

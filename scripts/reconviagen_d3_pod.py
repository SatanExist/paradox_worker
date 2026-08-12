"""D3 ReconViaGen v0.5: create RunPod → oneshot Armor F+B → download GLB → terminate.

Heavy first run (conda + setup.sh + HF weights): 1–3h. Prefer A6000/4090.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\reconviagen_d3_pod.py
  .\\.venv\\Scripts\\python.exe scripts\\reconviagen_d3_pod.py --no-run   # create + keep
  .\\.venv\\Scripts\\python.exe scripts\\reconviagen_d3_pod.py --keep     # leave pod up
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
# Attach T2 HF cache if present (EU-RO-1).
NETWORK_VOLUME_ID = os.getenv("RUNPOD_T2_VOLUME_ID", "netu72a8j2")
GPU_CANDIDATES = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA RTX A6000",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA L40",
    "NVIDIA L40S",
    "NVIDIA RTX A5000",
    "NVIDIA GeForce RTX 3090",
    "NVIDIA A40",
]
SSH_KEY = Path(os.getenv("RUNPOD_SSH_KEY", Path.home() / ".ssh" / "id_ed25519"))
SSH_PUB = Path(os.getenv("RUNPOD_SSH_PUBKEY", str(SSH_KEY) + ".pub"))


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise SystemExit("RUNPOD_API_KEY missing in .env")
    return key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _read_pubkey() -> str:
    if SSH_PUB.is_file():
        return SSH_PUB.read_text(encoding="utf-8").strip()
    return os.getenv("RUNPOD_SSH_PUBLIC_KEY", "").strip()


def create_pod(*, name: str, disk_gb: int, use_volume: bool, cloud_type: str = "SECURE") -> dict:
    pubkey = _read_pubkey()
    env: dict[str, str] = {
        "HF_HOME": "/runpod-volume/huggingface_cache" if use_volume else "/workspace/hf_cache",
    }
    if pubkey:
        env["PUBLIC_KEY"] = pubkey
        print(f"Injecting PUBLIC_KEY from {SSH_PUB if SSH_PUB.is_file() else 'env'}")
    token = os.getenv("HF_TOKEN", "").strip()
    if token:
        env["HF_TOKEN"] = token
        env["HUGGING_FACE_HUB_TOKEN"] = token

    body: dict = {
        "name": name,
        "imageName": PUBLIC_IMAGE,
        "gpuTypeIds": GPU_CANDIDATES[:1],
        "gpuCount": 1,
        "containerDiskInGb": disk_gb,
        "ports": ["8888/http", "22/tcp"],
        "dockerStartCmd": ["sleep", "infinity"],
        "cloudType": cloud_type,
        "supportPublicIp": True,
        "env": env,
    }
    if use_volume:
        # Must land in EU-RO-1 with paradox-trellis2.
        body["networkVolumeId"] = NETWORK_VOLUME_ID
        body["volumeMountPath"] = "/runpod-volume"
        body["volumeInGb"] = 0
        print(f"Attaching networkVolumeId={NETWORK_VOLUME_ID} -> /runpod-volume")
    else:
        body["volumeInGb"] = 40
        body["volumeMountPath"] = "/workspace"

    last_err = ""
    for gpu in GPU_CANDIDATES:
        body["gpuTypeIds"] = [gpu]
        print(f"Creating pod gpu={gpu!r} image={PUBLIC_IMAGE!r} disk={disk_gb}G cloud={cloud_type} ...", flush=True)
        r = requests.post(f"{REST}/pods", headers=_headers(), json=body, timeout=120)
        if r.status_code < 400:
            pod = r.json() if r.content else {}
            print(f"Created pod id={pod.get('id')}", flush=True)
            return pod
        last_err = r.text[:800]
        print(f"  failed HTTP {r.status_code}: {last_err}", flush=True)
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
            "runtime { ports { ip isIpPublic publicPort privatePort type } } } }"
        ),
        "variables": {"id": pod_id},
    }
    gr = requests.post(f"{GQL}?api_key={key}", json=query, timeout=60)
    if not gr.ok:
        return None
    data = gr.json()
    if data.get("errors"):
        print(f"  GraphQL ports error: {data['errors'][0].get('message')}")
        return None
    pod = (data.get("data") or {}).get("pod") or {}
    runtime = pod.get("runtime") or {}
    ports = runtime.get("ports") or []
    best: tuple[str, int] | None = None
    for p in ports:
        if int(p.get("privatePort") or 0) != 22:
            continue
        ip = p.get("ip")
        pub = p.get("publicPort")
        if not ip or not pub:
            continue
        cand = (str(ip), int(pub))
        if p.get("isIpPublic") or p.get("type") == "tcp":
            best = cand
            if p.get("isIpPublic"):
                return best
        elif best is None:
            best = cand
    return best


def wait_ssh_ready(pod_id: str, *, timeout_s: int = 900) -> tuple[str, int]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            lr = requests.get(f"{REST}/pods", headers=_headers(), timeout=60)
            if lr.ok:
                pods = lr.json() if isinstance(lr.json(), list) else (lr.json().get("pods") or [])
                for pod in pods:
                    if isinstance(pod, dict) and pod.get("id") == pod_id:
                        print(f"  status={pod.get('desiredStatus')} ip={pod.get('publicIp')!r}")
                        break
        except Exception as exc:
            print(f"  REST list err: {exc}")
        rt = _pod_runtime_ports(pod_id)
        if rt:
            print(f"  SSH candidate {rt[0]}:{rt[1]}")
            return rt
        time.sleep(15)
    raise TimeoutError(f"Pod {pod_id} SSH not ready within {timeout_s}s")


def _ssh_cmd(ip: str, port: int, remote_cmd: str, *, timeout: int = 14400) -> int:
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
    return subprocess.call(cmd, timeout=600)


def _scp_pull(ip: str, port: int, remote: str, local: Path) -> int:
    local.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-P",
        str(port),
        "-i",
        str(SSH_KEY),
        f"root@{ip}:{remote}",
        str(local),
    ]
    print("SCP pull:", " ".join(cmd))
    return subprocess.call(cmd, timeout=600)


def build_upload_zip(zip_path: Path) -> Path:
    front = ROOT / "preview_textures" / "gemini_mv" / "front.png"
    back = ROOT / "preview_textures" / "gemini_mv" / "back.png"
    infer = ROOT / "scripts" / "reconviagen_infer.py"
    oneshot = ROOT / "scripts" / "reconviagen_d3_oneshot.sh"
    for p in (front, back, infer, oneshot):
        if not p.is_file():
            raise SystemExit(f"Missing upload file: {p}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(front, "data/front.png")
        zf.write(back, "data/back.png")
        zf.write(infer, "scripts/reconviagen_infer.py")
        zf.write(oneshot, "scripts/reconviagen_d3_oneshot.sh")
    print(f"Upload zip: {zip_path} ({zip_path.stat().st_size} bytes)")
    return zip_path


def main() -> int:
    p = argparse.ArgumentParser(description="D3 ReconViaGen pod automation")
    p.add_argument("--no-run", action="store_true", help="Create pod only; print manual steps")
    p.add_argument("--name", default="paradox-reconviagen-d3")
    p.add_argument("--disk-gb", type=int, default=100)
    p.add_argument("--no-volume", action="store_true", help="Do not attach paradox-trellis2 volume")
    p.add_argument(
        "--community",
        action="store_true",
        help="Use COMMUNITY cloud (more GPU stock)",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Do NOT terminate (debug / long install)",
    )
    args = p.parse_args()

    zip_local = ROOT / "reconviagen_d3_upload.zip"
    build_upload_zip(zip_local)

    one_liner = (
        "cd /workspace && unzip -o /tmp/reconviagen_d3_upload.zip -d /workspace "
        "&& sed -i 's/\\r$//' /workspace/scripts/reconviagen_d3_oneshot.sh "
        "&& bash /workspace/scripts/reconviagen_d3_oneshot.sh"
    )

    pod_id: str | None = None
    try:
        pod = create_pod(
            name=args.name,
            disk_gb=args.disk_gb,
            use_volume=not args.no_volume,
            cloud_type="COMMUNITY" if args.community else "SECURE",
        )
        pod_id = str(pod.get("id") or "")
        if not pod_id:
            raise SystemExit(f"No pod id in response: {pod}")

        print("\nWeb Terminal one-liner (after SCP zip to /tmp/reconviagen_d3_upload.zip):")
        print(one_liner)
        print(f"\nAfter DONE: download /workspace/outputs/r_pod_armor_fb.glb then terminate {pod_id}")

        if args.no_run:
            args.keep = True
            print(f"\nPod {pod_id} - manual mode (--no-run implies --keep).")
            print(
                f"  .\\.venv\\Scripts\\python.exe scripts\\mvadapter_create_pod.py "
                f"--terminate {pod_id}"
            )
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
            print("SSH failed - use Web Terminal one-liner above, then terminate.")
            args.keep = True
            return 1

        print("Uploading zip + starting D3 oneshot in nohup (1–3h; SSH may disconnect) ...")
        rc = _scp_file(ip, port, zip_local, "/tmp/reconviagen_d3_upload.zip")
        if rc != 0:
            print("SCP zip failed", file=sys.stderr)
            args.keep = True
            return rc

        boot = (
            "mkdir -p /workspace/logs && "
            "cd /workspace && unzip -o /tmp/reconviagen_d3_upload.zip -d /workspace && "
            "sed -i 's/\\r$//' /workspace/scripts/reconviagen_d3_oneshot.sh && "
            "nohup bash /workspace/scripts/reconviagen_d3_oneshot.sh "
            ">/workspace/logs/d3_nohup.out 2>&1 & echo $! > /workspace/logs/d3.pid && "
            "echo STARTED_PID=$(cat /workspace/logs/d3.pid)"
        )
        rc = _ssh_cmd(ip, port, boot, timeout=300)
        if rc != 0:
            print(f"Failed to start oneshot rc={rc}", file=sys.stderr)
            args.keep = True
            return rc

        # Poll for GLB up to 3.5h
        out_remote = "/workspace/outputs/r_pod_armor_fb.glb"
        out_local = ROOT / "preview_textures" / "reconviagen" / "r_pod_armor_fb.glb"
        deadline = time.time() + 3.5 * 3600
        while time.time() < deadline:
            check = (
                f"if [[ -f {out_remote} ]]; then echo GLB_READY $(stat -c%s {out_remote}); "
                f"elif grep -q 'D3 DONE' /workspace/logs/d3_reconviagen.log 2>/dev/null; then echo DONE_NO_GLB; "
                f"elif grep -qiE 'error|traceback|failed' /workspace/logs/d3_reconviagen.log 2>/dev/null "
                f"&& ! pgrep -f reconviagen_d3_oneshot >/dev/null; then echo FAILED; "
                f"else echo WAIT tail=$(tail -n1 /workspace/logs/d3_reconviagen.log 2>/dev/null | tr -d '\\r'); fi"
            )
            # Capture SSH stdout
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
                check,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                line = (proc.stdout or "").strip().splitlines()
                msg = line[-1] if line else f"rc={proc.returncode}"
                print(f"  poll: {msg}")
                if msg.startswith("GLB_READY"):
                    rc = _scp_pull(ip, port, out_remote, out_local)
                    if rc != 0:
                        args.keep = True
                        return rc
                    print(f"GLB saved -> {out_local} ({out_local.stat().st_size} bytes)")
                    # also pull log
                    _scp_pull(
                        ip,
                        port,
                        "/workspace/logs/d3_reconviagen.log",
                        ROOT / "preview_textures" / "reconviagen" / "d3_reconviagen.log",
                    )
                    return 0
                if msg.startswith("FAILED") or msg.startswith("DONE_NO_GLB"):
                    _scp_pull(
                        ip,
                        port,
                        "/workspace/logs/d3_reconviagen.log",
                        ROOT / "preview_textures" / "reconviagen" / "d3_reconviagen.log",
                    )
                    args.keep = True
                    return 1
            except Exception as exc:
                print(f"  poll err: {exc}")
            time.sleep(60)

        print("Timed out waiting for GLB", file=sys.stderr)
        args.keep = True
        return 1
    finally:
        if pod_id and not args.keep:
            terminate_pod(pod_id)
        elif pod_id and args.keep:
            print(f"WARNING: --keep / failed; pod {pod_id} still RUNNING - terminate ASAP")


if __name__ == "__main__":
    raise SystemExit(main())

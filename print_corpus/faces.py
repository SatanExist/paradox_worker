"""Triangle count of a GLB from its JSON header only (no geometry load, works for Draco too)."""
import json, struct, sys
from pathlib import Path

def glb_faces(path: Path) -> int:
    with open(path, "rb") as f:
        f.read(12)
        n, _ = struct.unpack("<II", f.read(8))
        doc = json.loads(f.read(n))
    acc, total = doc.get("accessors", []), 0
    for mesh in doc.get("meshes", []):
        for p in mesh.get("primitives", []):
            if p.get("mode", 4) != 4:
                continue
            if "indices" in p:
                total += acc[p["indices"]]["count"] // 3
            else:
                total += acc[p["attributes"]["POSITION"]]["count"] // 3
    return total

if __name__ == "__main__":
    for p in sorted(Path(__file__).parent.glob("models/*.glb")):
        print(f"{glb_faces(p):>9} {p.stem}")

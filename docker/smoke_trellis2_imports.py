"""Import smoke test for TRELLIS.2 Docker build (CUDA stub libs required)."""
from __future__ import annotations

import sys
import traceback

MODULES = ("cumesh", "flex_gemm", "o_voxel", "trellis2")


def main() -> int:
    for name in MODULES:
        try:
            __import__(name)
            print(f"{name}: OK")
        except Exception:
            traceback.print_exc()
            print(f"import failed: {name}", file=sys.stderr)
            return 1
    print("all imports OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

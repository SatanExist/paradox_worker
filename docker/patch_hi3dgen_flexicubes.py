"""Build-time patch: restore FlexiCubes mesh extract on cloned Stable3DGen.

Upstream GitHub replaced FlexiCubes with skimage marching cubes (NVIDIA license).
The TRELLIS-normal decoder still emits the 21 FlexiCubes weights; MC ignores them
and the surface looks soapy (#36). FlexiCubes is Apache-2.0 as of 2025.

We clone MaxtirError/FlexiCubes (relative imports + vertex attrs) and drop the
kaolin.utils.testing.check_tensor import so the Hi3DGen image stays free of
kaolin/nvdiffrast.
"""

from __future__ import annotations

from pathlib import Path

MESH = Path("/app/Stable3DGen/hi3dgen/representations/mesh")
FLEX = MESH / "flexicubes" / "flexicubes.py"
CUBE = MESH / "cube2mesh.py"

KAOLIN_IMPORT = "from kaolin.utils.testing import check_tensor\n"
CHECK_TENSOR = '''def check_tensor(tensor, shape, throw=False):
    """Local stand-in for kaolin.utils.testing.check_tensor (inference only)."""
    ok = torch.is_tensor(tensor) and getattr(tensor, "ndim", -1) == len(shape)
    if ok:
        for i, s in enumerate(shape):
            if s is not None and int(tensor.shape[i]) != int(s):
                ok = False
                break
    if throw and not ok:
        raise ValueError(
            f"check_tensor failed: expected {shape}, got "
            f"{tuple(tensor.shape) if torch.is_tensor(tensor) else type(tensor)}"
        )
    return ok

'''

SPARSE_FEATURES2MESH = '''class SparseFeatures2Mesh:
    def __init__(self, device="cuda", res=128, use_color=True):
        """Sparse voxel features → mesh. Default FlexiCubes (trained layout)."""
        super().__init__()
        self.device = device
        self.res = res
        self.use_color = use_color
        mode = os.environ.get("HI3DGEN_MESH_EXTRACT", "flexicubes").strip().lower()
        self.extract_mode = "mc" if mode in ("mc", "marching_cubes") else "flexicubes"
        if self.extract_mode == "mc":
            self.mesh_extractor = EnhancedMarchingCubes(device=device)
        else:
            self.mesh_extractor = FlexiCubes(device=device)
        self.sdf_bias = -1.0 / res
        verts, cube = construct_dense_grid(self.res, self.device)
        self.reg_c = cube.to(self.device)
        self.reg_v = verts.to(self.device)
        self._calc_layout()

    def _calc_layout(self):
        LAYOUTS = {
            "sdf": {"shape": (8, 1), "size": 8},
            "deform": {"shape": (8, 3), "size": 8 * 3},
            "weights": {"shape": (21,), "size": 21},
        }
        if self.use_color:
            LAYOUTS["color"] = {"shape": (8, 6,), "size": 8 * 6}
        self.layouts = LAYOUTS
        start = 0
        for k, v in self.layouts.items():
            v["range"] = (start, start + v["size"])
            start += v["size"]
        self.feats_channels = start

    def get_layout(self, feats: torch.Tensor, name: str):
        if name not in self.layouts:
            return None
        return feats[:, self.layouts[name]["range"][0]:self.layouts[name]["range"][1]].reshape(
            -1, *self.layouts[name]["shape"]
        )

    def __call__(self, cubefeats: SparseTensor, training=False):
        coords = cubefeats.coords[:, 1:]
        feats = cubefeats.feats

        sdf, deform, color, weights = [
            self.get_layout(feats, name) for name in ["sdf", "deform", "color", "weights"]
        ]
        sdf += self.sdf_bias
        v_attrs = [sdf, deform, color] if self.use_color else [sdf, deform]
        v_pos, v_attrs, reg_loss = sparse_cube2verts(
            coords, torch.cat(v_attrs, dim=-1), training=training
        )
        v_attrs_d = get_dense_attrs(v_pos, v_attrs, res=self.res + 1, sdf_init=True)
        if self.use_color:
            sdf_d, deform_d, colors_d = (
                v_attrs_d[..., 0],
                v_attrs_d[..., 1:4],
                v_attrs_d[..., 4:],
            )
        else:
            sdf_d, deform_d = v_attrs_d[..., 0], v_attrs_d[..., 1:4]
            colors_d = None

        x_nx3 = get_defomed_verts(self.reg_v, deform_d, self.res)

        if self.extract_mode == "mc":
            vertices, faces, L_dev, colors = self.mesh_extractor(
                voxelgrid_vertices=x_nx3,
                scalar_field=sdf_d,
                voxelgrid_colors=colors_d,
                training=training,
            )
        else:
            weights_d = get_dense_attrs(coords, weights, res=self.res, sdf_init=False)
            vertices, faces, L_dev, colors = self.mesh_extractor(
                voxelgrid_vertices=x_nx3,
                scalar_field=sdf_d,
                cube_idx=self.reg_c,
                resolution=self.res,
                beta=weights_d[:, :12],
                alpha=weights_d[:, 12:20],
                gamma_f=weights_d[:, 20],
                voxelgrid_colors=colors_d,
                training=training,
            )

        mesh = MeshExtractResult(
            vertices=vertices, faces=faces, vertex_attrs=colors, res=self.res
        )
        if training:
            if mesh.success:
                reg_loss += L_dev.mean() * 0.5
            if weights is not None:
                reg_loss += (weights[:, :20]).abs().mean() * 0.2
            mesh.reg_loss = reg_loss
            mesh.tsdf_v = get_defomed_verts(v_pos, v_attrs[:, 1:4], self.res)
            mesh.tsdf_s = v_attrs[:, 0]
        return mesh
'''


def main() -> None:
    src = FLEX.read_text(encoding="utf-8")
    if KAOLIN_IMPORT not in src:
        raise SystemExit("kaolin import not found in flexicubes.py")
    FLEX.write_text(src.replace(KAOLIN_IMPORT, CHECK_TENSOR, 1), encoding="utf-8")

    cube = CUBE.read_text(encoding="utf-8")
    if "from .flexicubes.flexicubes import FlexiCubes" not in cube:
        needle = "from skimage import measure\n"
        if needle not in cube:
            raise SystemExit("skimage import not found in cube2mesh.py")
        cube = cube.replace(
            needle,
            needle + "from .flexicubes.flexicubes import FlexiCubes\nimport os\n",
            1,
        )
    marker = "class SparseFeatures2Mesh:"
    idx = cube.find(marker)
    if idx < 0:
        raise SystemExit("SparseFeatures2Mesh not found")
    CUBE.write_text(cube[:idx] + SPARSE_FEATURES2MESH, encoding="utf-8")
    print("patched cube2mesh + flexicubes (no kaolin)")


if __name__ == "__main__":
    main()

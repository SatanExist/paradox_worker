"""flash_attn's API on top of PyTorch SDPA, the same file the dev PC runs (flash-attn does not build on Windows).
SkinTokens' skin VAE imports flash_attn.flash_attn_interface.flash_attn_func; the rig image installs this package
under that name so the server computes attention exactly as the PC where the rigs were checked. Real flash-attn 2
(Linux wheels exist) would be faster but would change the numbers: a later, separately checked step."""
__version__ = "2.0.0.shim"

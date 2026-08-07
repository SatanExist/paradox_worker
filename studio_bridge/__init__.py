"""AI_MESH Studio bridge package.

Import submodules directly (e.g. studio_bridge.mesh_repair) to avoid pulling
optional deps required by the Studio HTTP service.
"""

__all__ = ["TierName", "create_job", "get_job"]


def __getattr__(name: str):
    if name == "TierName":
        from studio_bridge.tiers import TierName

        return TierName
    if name in ("create_job", "get_job"):
        from studio_bridge.service import create_job, get_job

        return create_job if name == "create_job" else get_job
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

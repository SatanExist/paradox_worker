"""SkinTokens' bpy server, but every request starts from the same random state: it samples surface points and jitters
joints with np.random / random, so without this the network input changes from run to run (same model -> other rig).
Runs in the SkinTokens venv with cwd = the SkinTokens folder (started by autorig.py)."""
import os
import random
import sys

sys.path.insert(0, os.getcwd())
import bottle  # noqa: E402
import numpy as np  # noqa: E402

SEED = 12345


def _seeded(callback):
    def wrapper(*a, **k):
        random.seed(SEED)
        np.random.seed(SEED)
        return callback(*a, **k)
    return wrapper


_init = bottle.Bottle.__init__


def _patched_init(self, *a, **k):
    _init(self, *a, **k)
    self.install(_seeded)


bottle.Bottle.__init__ = _patched_init

if __name__ == "__main__":
    from src.server.bpy_server import run
    run()

"""Warnings for limbs the generator grew together (an arm stuck to the flank): the model has no skin there, so a gap shows
when they move apart. Like Mixamo / AccuRIG we do not invent the missing skin; we say so and how to avoid it.
The measure comes from inner.py (CHECK=1): skin two parts share where the model has no skin of its own, in
cross-sections of the limb."""

# Below a tenth of a limb cross-section nothing shows. On the 9 test rigs the models with a visible gap measure 0.36 and
# up and the models without one exactly 0: a chosen number, far from both groups, not fitted to their edge.
NOISE = 0.1


def warnings(groups, noise=NOISE):
    out = []
    for g in groups:
        if g["sections"] < noise:
            continue
        a, b = g["parts"]
        if "body" in (a, b):
            limb = b if a == "body" else a
            out.append(f"warning: the {limb} is grown into the body (the model has no skin there), so a gap shows when "
                       f"it moves away; for a clean rig use a model made with the {'arms' if 'arm' in limb else 'legs'} "
                       f"apart from the body (A-pose or T-pose)")
        elif "leg" in a and "leg" in b:
            out.append("warning: the legs are grown together (like a long robe), so walking tears them open; for a "
                       "clean rig use a model with the legs apart")
        else:
            out.append(f"warning: the {a} and the {b} are grown together, so a gap shows when they move apart; for a "
                       f"clean rig use a model where they do not touch")
    return out

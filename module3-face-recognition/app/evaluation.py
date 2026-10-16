"""Aggregate evaluation statistics; never select a production threshold here."""

import math


def rate(errors, total):
    if not total:
        return {"errors": errors, "total": total, "rate": None, "wilson_95": None}
    p = errors / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"errors": errors, "total": total, "rate": p,
            "wilson_95": [max(0., center - radius), min(1., center + radius)]}


def summarize(rows, threshold, kind):
    """Rows are (expected_positive, score, eligible); HTTP failures excluded.

    Identity: FAR = accepted impostors / impostor comparisons, FRR = rejected
    genuine comparisons / genuine comparisons. PAD: APCER = accepted attacks /
    attacks, BPCER = rejected bona-fide presentations / bona-fide presentations.
    """
    negatives = [row for row in rows if not row[0]]
    positives = [row for row in rows if row[0]]
    accepted_wrong = sum(eligible and score >= threshold for _, score, eligible in negatives)
    rejected_right = sum(not eligible or score < threshold for _, score, eligible in positives)
    names = ("FAR", "FRR") if kind == "identity" else ("APCER", "BPCER")
    return {"threshold": threshold, names[0]: rate(accepted_wrong, len(negatives)),
            names[1]: rate(rejected_right, len(positives))}

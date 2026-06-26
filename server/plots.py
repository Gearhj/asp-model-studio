# server/plots.py
from io import BytesIO
from typing import List, Optional, Tuple
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn import metrics

sns.set_theme(style="whitegrid", font_scale=1.0)
plt.rcParams["figure.dpi"] = 180
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 11

def _png_bytes(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def _arr(a):  # small helper
    return np.array(a if a is not None else [], dtype=float)

def roc_png(
    y=None, yhat=None, roc_x=None, roc_y=None,
    f1_fpr=None, maxp_fpr=None, maxr_fpr=None, auc=None,
) -> bytes:
    y_arr, s_arr = _arr(y), _arr(yhat)
    if y_arr.size and s_arr.size and y_arr.size == s_arr.size:
        fpr, tpr, _ = metrics.roc_curve(y_arr, s_arr)
        auc_val = metrics.auc(fpr, tpr)
    else:
        fpr, tpr = _arr(roc_x), _arr(roc_y)
        auc_val = float(auc or 0.0)

    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.plot(fpr, tpr, color="#2563EB", lw=2, label="ROC curve")
    ax.plot([0, 1], [0, 1], color="#9CA3AF", lw=1, ls="--", label="45° baseline")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("False Positive Rate"); ax.set_ylabel("True Positive Rate")
    ax.set_title(f"ROC Curve (AUC = {auc_val:.3f})")

    markers = [
        (f1_fpr,  "#10B981", "F1-optimal"),
        (maxp_fpr, "#7C3AED", "Max Precision"),
        (maxr_fpr, "#EF4444", "Max Recall"),
    ]
    for v, c, lbl in markers:
        if v is not None:
            ax.axvline(v, color=c, ls=(0, (4, 6)), lw=1.5, label=lbl)
    ax.legend(frameon=True, loc="lower right")
    return _png_bytes(fig)

def pr_png(
    y=None, yhat=None, pr_x=None, pr_y=None,
    f1_rec=None, maxp_rec=None, maxr_rec=None,
) -> bytes:
    y_arr, s_arr = _arr(y), _arr(yhat)
    if y_arr.size and s_arr.size and y_arr.size == s_arr.size:
        precision, recall, _ = metrics.precision_recall_curve(y_arr, s_arr)
    else:
        recall, precision = _arr(pr_x), _arr(pr_y)

    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.plot(recall, precision, color="#7C3AED", lw=2, label="PR curve")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("Recall"); ax.set_ylabel("Precision")
    ax.set_title("Precision–Recall Curve")

    markers = [
        (f1_rec,  "#10B981", "F1-optimal"),
        (maxp_rec, "#7C3AED", "Max Precision"),
        (maxr_rec, "#EF4444", "Max Recall"),
    ]
    for v, c, lbl in markers:
        if v is not None:
            ax.axvline(v, color=c, ls=(0, (4, 6)), lw=1.5, label=lbl)
    ax.legend(frameon=True, loc="upper right")
    return _png_bytes(fig)

def decile_lift(y: List[int], yhat: List[float]):
    y_arr = np.asarray(y, dtype=int)
    s_arr = np.asarray(yhat, dtype=float)
    assert y_arr.shape == s_arr.shape and y_arr.size > 0, "y and yhat must align"

    n = y_arr.size
    base_pos = int((y_arr == 1).sum())
    base_rate = base_pos / n if n else 0.0

    order = np.argsort(-s_arr)  # desc by score
    y_sorted = y_arr[order]
    size = n // 10
    rows = []; cum_pos = 0
    for d in range(10):
        start = d * size
        end = n if d == 9 else (d + 1) * size
        yi = y_sorted[start:end]
        N = yi.size
        pos = int((yi == 1).sum())
        cum_pos += pos
        resp = (pos / N) if N else 0.0
        rows.append({
            "decile": d + 1,
            "n": int(N),
            "positives": int(pos),
            "responseRate": resp,
            "lift": (resp / base_rate) if base_rate > 0 else 0.0,
            "cumCapture": (cum_pos / base_pos) if base_pos > 0 else 0.0,
        })
    return {"baseRate": base_rate, "total": int(n), "positives": int(base_pos), "rows": rows}

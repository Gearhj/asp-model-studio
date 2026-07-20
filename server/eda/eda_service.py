# server/eda/eda_service.py
# =============================================================================
# EDA Service: numeric summaries + D3-friendly payloads + PNG images
# =============================================================================

from __future__ import annotations
from typing import Dict, Any, List, Optional

import io
import base64

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None

try:
    import seaborn as sns
except Exception:  # pragma: no cover
    sns = None


# ----------------------------------------------------------------------------- 
# helpers
# -----------------------------------------------------------------------------
def _coerce_numeric_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a numeric-only DataFrame by trying to coerce each column to float.

    This lets us handle FinServ-style CSVs where numeric fields come in as
    strings (e.g., '12', '3.5', '0').
    """
    if df is None or df.empty:
        return pd.DataFrame()

    numeric_cols: Dict[str, pd.Series] = {}
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce")
        # keep column if it has at least 2 non-null values
        if s.notna().sum() >= 2:
            numeric_cols[str(col)] = s

    if not numeric_cols:
        return pd.DataFrame()

    return pd.DataFrame(numeric_cols)


class EDAService:
    """EDA computation and image generation."""

    # ------------------------------------------------------------------
    # Tabular summaries
    # ------------------------------------------------------------------
    def dataset_overview(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": True, "n_rows": 0, "n_cols": 0}
        return {
            "ok": True,
            "n_rows": int(df.shape[0]),
            "n_cols": int(df.shape[1]),
        }

    def numeric_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": True, "rows": []}
        num_df = _coerce_numeric_df(df)
        if num_df.empty:
            return {"ok": True, "rows": []}
        desc = num_df.describe().T.reset_index().rename(columns={"index": "feature"})
        return {"ok": True, "rows": desc.to_dict(orient="records")}

    def missing_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": True, "rows": []}
        total = len(df)
        rows: List[Dict[str, Any]] = []
        for col in df.columns:
            n_missing = int(df[col].isna().sum())
            if n_missing == 0:
                continue
            rows.append(
                {
                    "feature": str(col),
                    "n_missing": n_missing,
                    "pct_missing": float(n_missing / total * 100.0),
                }
            )
        return {"ok": True, "rows": rows}

    def histogram(self, df: pd.DataFrame, column: str, bins: int = 40) -> Dict[str, Any]:
        if df is None or df.empty or column not in df.columns:
            return {"ok": False, "error": "Column not found."}
        s = pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if s.empty:
            return {"ok": False, "error": "No data for column."}
        requested_bins = min(max(5, int(bins)), 60)
        counts, edges = np.histogram(s.values, bins=requested_bins)
        return {
            "ok": True,
            "edges": edges.astype(float).tolist(),
            "counts": counts.astype(float).tolist(),
            "column": str(column),
            "requested_bins": requested_bins,
            "returned_bins": int(len(counts)),
            "row_count": int(len(s)),
        }

    def boxplot_stats(self, df: pd.DataFrame, column: str) -> Dict[str, Any]:
        if df is None or df.empty or column not in df.columns:
            return {"ok": False, "error": "Column not found."}
        s = pd.to_numeric(df[column], errors="coerce").dropna()
        if s.empty:
            return {"ok": False, "error": "No data for column."}
        q1 = float(s.quantile(0.25))
        q2 = float(s.quantile(0.5))
        q3 = float(s.quantile(0.75))
        iqr = q3 - q1
        whisker_low = float(max(s.min(), q1 - 1.5 * iqr))
        whisker_high = float(min(s.max(), q3 + 1.5 * iqr))
        return {
            "ok": True,
            "q1": q1,
            "median": q2,
            "q3": q3,
            "whisker_low": whisker_low,
            "whisker_high": whisker_high,
        }

    def correlation_matrix(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": True, "matrix": [], "columns": []}
        num_df = _coerce_numeric_df(df)
        if num_df.shape[1] < 2:
            return {"ok": True, "matrix": [], "columns": []}
        corr = num_df.corr()
        return {
            "ok": True,
            "matrix": corr.values.tolist(),
            "columns": [str(c) for c in corr.columns],
        }

    def sample_records(self, df: pd.DataFrame, max_rows: int = 10000) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": True, "headers": [], "rows": []}
        sample_df = df.head(max_rows)
        return {
            "ok": True,
            "headers": [str(c) for c in sample_df.columns],
            "rows": sample_df.to_dict(orient="records"),
        }

    # ------------------------------------------------------------------
    # D3 histogram payload for /api/eda/d3_histogram
    # ------------------------------------------------------------------
    def d3_histogram(
        self,
        df: pd.DataFrame,
        feature: str,
        target: Optional[str],
        bins: int = 20,
        sample_pct: int = 10,
    ) -> Dict[str, Any]:
        if df is None or df.empty or feature not in df.columns:
            return {"ok": False, "error": "Feature not found."}

        # cap rows for performance
        work_df = df
        if df.shape[0] > 20000:
            work_df = df.sample(n=20000, random_state=42)
        if 0 < sample_pct < 100:
            work_df = work_df.sample(
                frac=sample_pct / 100.0, random_state=42
            )

        s = pd.to_numeric(work_df[feature], errors="coerce").dropna()
        if s.empty:
            return {"ok": False, "error": "No numeric data for feature."}

        counts, edges = np.histogram(s.values, bins=bins)

        event_counts = None
        nonevent_counts = None
        tgt_name = None

        if target and target in work_df.columns:
            tgt = work_df[target]
            if tgt.dtype == bool or (
                pd.api.types.is_numeric_dtype(tgt)
                and len(pd.unique(tgt.dropna())) <= 2
            ):
                tgt_name = target
                uniq = sorted(pd.unique(tgt.dropna()))
                event_val = uniq[-1]
                mask_event = tgt == event_val
                mask_nonevent = ~mask_event

                s_event = pd.to_numeric(
                    work_df.loc[mask_event, feature], errors="coerce"
                ).dropna()
                s_nonevent = pd.to_numeric(
                    work_df.loc[mask_nonevent, feature], errors="coerce"
                ).dropna()
                if not s_event.empty:
                    event_counts, _ = np.histogram(s_event.values, bins=edges)
                if not s_nonevent.empty:
                    nonevent_counts, _ = np.histogram(s_nonevent.values, bins=edges)

        return {
            "ok": True,
            "edges": edges.astype(float).tolist(),
            "overall": counts.astype(float).tolist(),
            "event": None if event_counts is None else event_counts.astype(float).tolist(),
            "nonevent": None if nonevent_counts is None else nonevent_counts.astype(float).tolist(),
            "target_name": tgt_name,
        }

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------
    def _fig_to_b64(self) -> Optional[str]:
        if plt is None:
            return None
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")

    def boxplot_image(
        self,
        df: pd.DataFrame,
        feature: str,
        sample_pct: int = 10,
    ) -> Dict[str, Any]:
        if plt is None:
            return {"ok": False, "error": "matplotlib not available."}
        if df is None or df.empty or feature not in df.columns:
            return {"ok": False, "error": "Feature not found."}

        work_df = df
        if df.shape[0] > 20000:
            work_df = df.sample(n=20000, random_state=42)
        if 0 < sample_pct < 100:
            work_df = work_df.sample(
                frac=sample_pct / 100.0, random_state=42
            )

        s = pd.to_numeric(work_df[feature], errors="coerce").dropna()
        if s.empty:
            return {"ok": False, "error": "No numeric data for feature."}

        plt.figure(figsize=(4, 3))
        plt.boxplot(s.values, vert=True, labels=[feature])
        plt.title(f"Boxplot – {feature}")
        img_b64 = self._fig_to_b64()
        if not img_b64:
            return {"ok": False, "error": "Failed to render boxplot."}
        return {"ok": True, "image_b64": img_b64}

    def corr_heatmap_image(self, df: pd.DataFrame, sample_pct: int = 10, limit: int = 20) -> Dict[str, Any]:
        if plt is None or sns is None:
            return {"ok": False, "error": "matplotlib/seaborn not available."}
        if df is None or df.empty:
            return {"ok": False, "error": "No data."}

        work_df = df
        if df.shape[0] > 20000:
            work_df = df.sample(n=20000, random_state=42)
        if 0 < sample_pct < 100:
            work_df = work_df.sample(
                frac=sample_pct / 100.0, random_state=42
            )

        num_df = _coerce_numeric_df(work_df)
        if num_df.shape[1] < 2:
            return {"ok": False, "error": "Not enough numeric columns."}
        limit = max(2, min(20, int(limit or 20)))
        if num_df.shape[1] > limit:
            variances = num_df.var(numeric_only=True).abs().sort_values(ascending=False)
            keep_cols = [col for col in variances.index.tolist() if col in num_df.columns][:limit]
            num_df = num_df[keep_cols]

        corr = num_df.corr()

        size = max(6, min(13, 0.45 * len(corr.columns) + 3))
        plt.figure(figsize=(size, size * 0.82))
        sns.heatmap(corr, cmap="coolwarm", center=0, square=True, cbar=True, xticklabels=True, yticklabels=True)
        plt.xticks(rotation=45, ha="right", fontsize=8)
        plt.yticks(rotation=0, fontsize=8)
        plt.title(f"Correlation Heatmap - Top {len(corr.columns)} Numeric Features")
        img_b64 = self._fig_to_b64()
        if not img_b64:
            return {"ok": False, "error": "Failed to render heatmap."}
        return {"ok": True, "image_b64": img_b64}

    def pairplot_image(self, df: pd.DataFrame, sample_pct: int = 10) -> Dict[str, Any]:
        if plt is None or sns is None:
            return {"ok": False, "error": "matplotlib/seaborn not available."}
        if df is None or df.empty:
            return {"ok": False, "error": "No data."}

        work_df = df
        if df.shape[0] > 20000:
            work_df = df.sample(n=20000, random_state=42)
        if 0 < sample_pct < 100:
            work_df = work_df.sample(
                frac=sample_pct / 100.0, random_state=42
            )

        num_df = _coerce_numeric_df(work_df)
        if num_df.shape[1] < 2:
            return {"ok": False, "error": "Not enough numeric columns."}

        # Limit to max 5 numeric columns and ~2k rows for readability & speed
        if num_df.shape[1] > 5:
            num_df = num_df.iloc[:, :5]
        if num_df.shape[0] > 2000:
            num_df = num_df.sample(n=2000, random_state=42)

        sns_pair = sns.pairplot(num_df, diag_kind="hist")
        fig = sns_pair.fig
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("ascii")
        return {"ok": True, "image_b64": img_b64}


eda_service = EDAService()

"""
Demonstrates the 'Silent Lie': a typical pandas ingestion script that uses
errors='coerce' to avoid crashing, finishes with exit code 0, and outputs
wildly corrupted revenue numbers without raising a single warning.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
import pandas as pd
import psutil

DATA_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIR / "billing_events_500k.csv"
TRUTH_PATH = DATA_DIR / "ground_truth.json"


def run_naive_pipeline(csv_path: Path = CSV_PATH) -> dict:
    proc = psutil.Process(os.getpid())
    rss_before = proc.memory_info().rss / (1024 * 1024)
    t0 = time.perf_counter()

    df = pd.read_csv(csv_path, dtype=str)

    # Typical quick-fix code found in tutorials: coerce bad strings to NaN -> 0
    df["amount"] = pd.to_numeric(df["amount_raw"], errors="coerce").fillna(0.0)
    df["ts"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)

    naive_total = round(float(df["amount"].sum()), 2)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    rss_peak = round(proc.memory_info().rss / (1024 * 1024) - rss_before, 1)

    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8")) if TRUTH_PATH.exists() else {}
    true_rev = truth.get("true_clean_usd_revenue", 0.0)

    return {
        "pipeline": "naive_pandas_coerce",
        "exit_status": "SUCCESS (0 errors raised!)",
        "rows_counted": int(len(df)),
        "reported_revenue_usd": naive_total,
        "true_clean_revenue_usd": true_rev,
        "silent_dollar_error_usd": round(naive_total - true_rev, 2),
        "dropped_enterprise_invoices_usd": truth.get("formatted_enterprise_usd_at_risk", 0.0),
        "elapsed_ms": elapsed_ms,
        "memory_delta_mb": rss_peak,
    }


if __name__ == "__main__":
    result = run_naive_pipeline()
    print(json.dumps(result, indent=2))

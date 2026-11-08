"""
Vectorized Data Quarantine Gate + FastAPI Audit Endpoint.

Instead of crashing a 500k-row batch on the first bad row OR silently coercing
dirty values into 0, this gate evaluates vectorized masks, separates clean rows
from quarantined rows with explicit reason codes, and exposes an audit summary.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
import pandas as pd
import psutil
from fastapi import FastAPI

DATA_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIR / "billing_events_500k.csv"
CLEAN_OUT = DATA_DIR / "clean_events.csv"
QUARANTINE_OUT = DATA_DIR / "quarantined_events.csv"
TRUTH_PATH = DATA_DIR / "ground_truth.json"

MIN_VALID_TS = "2020-01-01T00:00:00Z"
MAX_SINGLE_CHARGE_USD = 10_000.00

app = FastAPI(title="Billing Feed Quarantine Gate", version="1.0.0")


def quarantine_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Split raw string DataFrame into (clean_df, quarantine_df, metrics)."""
    reasons = pd.Series("", index=df.index, dtype="object")

    # Rule 1: Currency unit must be exact 'USD' (catches 'USD_CENTS' before summing!)
    bad_unit = df["currency_unit"] != "USD"
    reasons = reasons.where(~bad_unit, reasons + "UNIT_NOT_USD;")

    # Rule 2: Strict numeric format without '$' or commas (no silent NaN->0 coercion)
    parsed_amount = pd.to_numeric(df["amount_raw"], errors="coerce")
    bad_number = parsed_amount.isna() | (parsed_amount <= 0) | (parsed_amount > MAX_SINGLE_CHARGE_USD)
    reasons = reasons.where(~bad_number, reasons + "UNPARSED_OR_OUT_OF_RANGE_AMOUNT;")

    # Rule 3: Timestamp sanity (catches 1970-01-01 Unix epoch fallbacks & invalid dates)
    parsed_ts = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    bad_ts = parsed_ts.isna() | (parsed_ts < pd.Timestamp(MIN_VALID_TS))
    reasons = reasons.where(~bad_ts, reasons + "INVALID_OR_EPOCH_TIMESTAMP;")

    # Rule 4: Duplicate webhook retry IDs (keep first occurrence only among otherwise-valid rows)
    dupe_id = df.duplicated(subset=["event_id"], keep="first")
    reasons = reasons.where(~dupe_id, reasons + "DUPLICATE_WEBHOOK_ID;")

    is_quarantined = reasons != ""

    clean_df = df.loc[~is_quarantined].copy()
    clean_df["amount_usd"] = parsed_amount.loc[~is_quarantined].astype(float)

    quarantine_df = df.loc[is_quarantined].copy()
    quarantine_df["quarantine_reason"] = reasons.loc[is_quarantined].str.rstrip(";")

    reason_counts = quarantine_df["quarantine_reason"].value_counts().to_dict()
    metrics = {
        "total_input_rows": int(len(df)),
        "clean_rows_accepted": int(len(clean_df)),
        "quarantined_rows_rejected": int(len(quarantine_df)),
        "verified_clean_revenue_usd": round(float(clean_df["amount_usd"].sum()), 2),
        "quarantine_breakdown": {str(k): int(v) for k, v in reason_counts.items()},
    }
    return clean_df, quarantine_df, metrics


def run_quarantine_file(csv_path: Path = CSV_PATH, write_outputs: bool = True) -> dict:
    proc = psutil.Process(os.getpid())
    rss_before = proc.memory_info().rss / (1024 * 1024)
    t0 = time.perf_counter()

    raw_df = pd.read_csv(csv_path, dtype=str)
    clean_df, quarantine_df, metrics = quarantine_dataframe(raw_df)

    if write_outputs:
        clean_df.to_csv(CLEAN_OUT, index=False)
        quarantine_df.to_csv(QUARANTINE_OUT, index=False)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    rss_delta = round(proc.memory_info().rss / (1024 * 1024) - rss_before, 1)

    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8")) if TRUTH_PATH.exists() else {}
    true_rev = truth.get("true_clean_revenue_usd", truth.get("true_clean_usd_revenue", 0.0))

    metrics.update({
        "pipeline": "vectorized_quarantine_gate",
        "true_clean_revenue_usd": true_rev,
        "revenue_discrepancy_usd": round(metrics["verified_clean_revenue_usd"] - true_rev, 2),
        "elapsed_ms": elapsed_ms,
        "memory_delta_mb": rss_delta,
    })
    return metrics


@app.post("/ingest-audit")
def ingest_audit_endpoint() -> dict:
    """Trigger batch audit and return clean vs. quarantined summary."""
    return run_quarantine_file(write_outputs=False)


if __name__ == "__main__":
    summary = run_quarantine_file(write_outputs=True)
    print(json.dumps(summary, indent=2))

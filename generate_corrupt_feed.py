"""
Generate a reproducible 500,000-row SaaS billing CSV feed containing realistic
silent corruption patterns (webhook retries, currency strings, cents/dollars mix,
and epoch-zero timestamps) alongside exact ground-truth revenue totals.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIR / "billing_events_500k.csv"
TRUTH_PATH = DATA_DIR / "ground_truth.json"


def generate_feed(n_valid: int = 485_000, seed: int = 42) -> dict:
    t0 = time.perf_counter()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    # 1. Clean baseline SaaS subscription charges ($19, $49, $99, $299)
    plans = np.array([19.00, 49.00, 99.00, 299.00])
    amounts = rng.choice(plans, size=n_valid, p=[0.45, 0.35, 0.15, 0.05])
    true_revenue = float(np.round(amounts.sum(), 2))

    event_ids = [f"evt_{i:07d}" for i in range(1, n_valid + 1)]
    base_ts = pd.Timestamp("2026-10-01T00:00:00Z").value // 10**9
    offsets = rng.integers(0, 30 * 86400, size=n_valid)
    timestamps = pd.to_datetime(base_ts + offsets, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
    units = ["USD"] * n_valid

    df_clean = pd.DataFrame({
        "event_id": event_ids,
        "created_at": timestamps,
        "amount_raw": [f"{a:.2f}" for a in amounts],
        "currency_unit": units,
    })

    # Corrupt Pattern A: 5,000 enterprise invoices formatted with '$' and commas ("$1,299.00")
    # These ARE valid charges that belong in revenue if parsed properly, or quarantined if strict!
    # Here we treat unparsed currency strings as format violations that naive to_numeric turns to NaN -> 0.
    n_fmt = 5_000
    fmt_amounts = rng.choice([1299.00, 2499.00], size=n_fmt)
    true_enterprise_revenue = float(np.round(fmt_amounts.sum(), 2))
    df_fmt = pd.DataFrame({
        "event_id": [f"evt_ent_{i:05d}" for i in range(n_fmt)],
        "created_at": "2026-10-15T12:00:00Z",
        "amount_raw": [f"${a:,.2f}" for a in fmt_amounts],
        "currency_unit": "USD",
    })

    # Corrupt Pattern B: 5,000 duplicate webhook retries (exact copies of clean rows)
    df_dupes = df_clean.iloc[:5_000].copy()

    # Corrupt Pattern C: 3,000 legacy webhook rows sending CENTS (e.g. 4900 instead of 49.00)
    n_cents = 3_000
    df_cents = pd.DataFrame({
        "event_id": [f"evt_leg_{i:05d}" for i in range(n_cents)],
        "created_at": "2026-10-18T08:30:00Z",
        "amount_raw": [str(int(a * 100)) for a in rng.choice([49.00, 99.00], size=n_cents)],
        "currency_unit": "USD_CENTS",
    })

    # Corrupt Pattern D: 2,000 broken clock / null fallback rows at Unix epoch 1970-01-01
    n_epoch = 2_000
    df_epoch = pd.DataFrame({
        "event_id": [f"evt_badts_{i:05d}" for i in range(n_epoch)],
        "created_at": "1970-01-01T00:00:00Z",
        "amount_raw": "49.00",
        "currency_unit": "USD",
    })

    full_df = pd.concat([df_clean, df_fmt, df_dupes, df_cents, df_epoch], ignore_index=True)
    # Shuffle deterministically so bad rows are scattered throughout the file
    full_df = full_df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    full_df.to_csv(CSV_PATH, index=False)

    elapsed = round(time.perf_counter() - t0, 3)
    truth = {
        "total_rows_on_disk": int(len(full_df)),
        "strictly_clean_rows": n_valid,
        "true_clean_usd_revenue": true_revenue,
        "formatted_enterprise_rows": n_fmt,
        "formatted_enterprise_usd_at_risk": true_enterprise_revenue,
        "duplicate_webhook_rows": len(df_dupes),
        "cents_mismatch_rows": n_cents,
        "epoch_timestamp_rows": n_epoch,
        "generation_seconds": elapsed,
    }
    TRUTH_PATH.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"Generated {len(full_df):,} rows at {CSV_PATH} in {elapsed}s")
    print(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    generate_feed()

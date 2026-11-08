# `silent-data-quarantine` — Catching Silent Data Corruption in Python Billing Feeds

A reproducible 500,000-row Python benchmark showing how standard `pandas.to_numeric(..., errors="coerce")` scripts silently corrupt financial totals without raising an exception—and how to replace them with a fast, vectorized **Quarantine Gate** + `FastAPI` audit endpoint.

## The Problem

Most Python ingestion scripts choose between two bad options:
1. **Crash the whole batch** on row #14 because one string has a `$` sign (`ValueError: could not convert string to float`).
2. **Silence errors with `errors="coerce"` and `.fillna(0)`**, which exits cleanly (`code 0`) while dropping formatted invoices (`"$1,299.00"` -> `0.0`), double-counting webhook retries, and mixing `USD_CENTS` (`4900`) with `USD` (`49.00`).

## Benchmark Results (500,000 Rows — Python 3.11)

| Pipeline | Exit Status | Reported Revenue | True Clean Revenue | Silent Dollar Error | Wall Time (incl. CSV I/O) | Memory Delta |
|---|---|---|---|---|---|---|
| **Naive `pandas` (`errors="coerce"`)** | `0` (No errors!) | `$49,472,490.00` | `$26,870,210.00` | **`+$22,602,280.00`** *(plus `$9.52M` dropped to `$0`)* | `2,483.4 ms` | `55.4 MB` |
| **Vectorized Quarantine Gate** | `0` (Audited) | **`$26,870,210.00`** | `$26,870,210.00` | **`$0.00`** (`15,000` bad rows isolated with reason codes) | `4,584.8 ms` *(writes 2 CSVs)* | `138.6 MB` |

## Quick Start (Run in 60 Seconds)

```bash
pip install -r requirements.txt

# 1. Run unit tests
python -m unittest test_quarantine.py -v

# 2. Generate the 500,000-row SaaS billing dataset
python generate_corrupt_feed.py

# 3. See how naive pandas silently lies by $22.6M without raising an error
python naive_pipeline.py

# 4. Run the vectorized quarantine gate (splits clean_events.csv & quarantined_events.csv)
python quarantine_gate.py
```

## Optional: Run the FastAPI Audit Endpoint

```bash
uvicorn quarantine_gate:app --reload --port 8000
curl -X POST http://127.0.0.1:8000/ingest-audit
```

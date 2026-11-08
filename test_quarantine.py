"""Unit tests verifying that every silent corruption pattern is quarantined."""
from __future__ import annotations

import unittest
import pandas as pd
from quarantine_gate import quarantine_dataframe


class TestQuarantineGate(unittest.TestCase):
    def test_catches_all_four_corruption_types(self) -> None:
        sample = pd.DataFrame([
            # 1. Valid charge
            {"event_id": "evt_1", "created_at": "2026-10-10T10:00:00Z", "amount_raw": "49.00", "currency_unit": "USD"},
            # 2. Formatted string that pd.to_numeric(errors='coerce') would silently turn into NaN -> 0
            {"event_id": "evt_2", "created_at": "2026-10-10T10:01:00Z", "amount_raw": "$1,299.00", "currency_unit": "USD"},
            # 3. Duplicate webhook retry
            {"event_id": "evt_1", "created_at": "2026-10-10T10:00:00Z", "amount_raw": "49.00", "currency_unit": "USD"},
            # 4. Legacy cents unit mismatch
            {"event_id": "evt_3", "created_at": "2026-10-10T10:02:00Z", "amount_raw": "4900", "currency_unit": "USD_CENTS"},
            # 5. Unix epoch-zero timestamp fallback
            {"event_id": "evt_4", "created_at": "1970-01-01T00:00:00Z", "amount_raw": "99.00", "currency_unit": "USD"},
        ])

        clean_df, quarantine_df, metrics = quarantine_dataframe(sample)

        self.assertEqual(metrics["clean_rows_accepted"], 1)
        self.assertEqual(metrics["quarantined_rows_rejected"], 4)
        self.assertAlmostEqual(metrics["verified_clean_revenue_usd"], 49.00, places=2)

        reasons = dict(zip(quarantine_df["event_id"], quarantine_df["quarantine_reason"]))
        self.assertIn("UNPARSED_OR_OUT_OF_RANGE_AMOUNT", reasons["evt_2"])
        self.assertIn("UNIT_NOT_USD", reasons["evt_3"])
        self.assertIn("INVALID_OR_EPOCH_TIMESTAMP", reasons["evt_4"])


if __name__ == "__main__":
    unittest.main()

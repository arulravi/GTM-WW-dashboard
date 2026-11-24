import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import refresh


class RefreshRegressionTests(unittest.TestCase):
    def test_build_data_preserves_shared_commentary_without_live_sql(self):
        commentary = {
            "l3:Sales Ops L3|__all|2026-Q4": {
                "Comp & Benefits__fcst_vs_wk10": "Persisted commentary",
                "Additional Notes": "Intentionally retained",
            }
        }
        empty = pd.DataFrame()
        with (
            patch.object(refresh.db, "opex_facts", return_value=empty),
            patch.object(refresh.db, "hc_facts", return_value=empty),
            patch.object(refresh.db, "current_quarter", return_value="2026-Q4"),
            patch.object(refresh.db, "hc_planning", return_value=empty),
            patch.object(refresh.db, "opex_gl", return_value=empty),
            patch.object(refresh.db, "hc_actuals_ending", return_value=empty),
            patch.object(refresh.db, "hc_by_role", return_value=empty),
            patch.object(refresh.db, "hc_role_ending", return_value=empty),
            patch.object(refresh.db, "hc_monthly_hires", return_value=empty),
            patch.object(refresh.db, "hc_monthly_pipeline", return_value=empty),
            patch.object(refresh.db, "hc_movement", return_value=empty),
            patch.object(refresh, "build_position_analysis", return_value=[]),
            patch.object(refresh, "build_pipeline_positions", return_value=[]),
            patch.object(refresh, "read_manual_inputs", return_value={}),
            patch.object(refresh, "resolve_shared_app_dir", return_value="isolated"),
            patch.object(refresh, "read_shared_data", return_value=commentary),
            patch.object(refresh, "rollover_snapshot_commentary", return_value=False),
        ):
            data = refresh.build_data()

        self.assertEqual(data["commentary"], commentary)
        self.assertEqual(data["meta"]["current_quarter"], "2026-Q4")
        self.assertEqual(data["opex"], [])
        self.assertEqual(data["hc"], [])

    def test_write_data_js_round_trips_payload_to_configured_directory(self):
        payload = {
            "meta": {"generated_at": "test"},
            "opex": [["L2", "L3", "L4", "Comp & Benefits", "2026-Q4", "fcst", 1.25]],
            "commentary": {"scope": {"Additional Notes": "Persisted"}},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(refresh, "DATA_DIR", temp_dir):
                output = Path(refresh.write_data_js(payload))

            self.assertEqual(output, Path(temp_dir) / "data.js")
            source = output.read_text(encoding="utf-8")
            self.assertTrue(source.startswith("window.OPEX_DATA = "))
            restored = json.loads(
                source.removeprefix("window.OPEX_DATA = ").strip().removesuffix(";")
            )
            self.assertEqual(restored, payload)


if __name__ == "__main__":
    unittest.main()

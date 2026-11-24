import unittest

import pandas as pd

from fiscal import Scenario
from transform import build_opex_walk, collapse_headcount, per_head_metrics, variances


class FinancialTransformTests(unittest.TestCase):
    def test_opex_walk_and_variance_preserve_million_units_and_sign(self):
        scenarios = [
            Scenario("FY26 Plan", "plan", "plan"),
            Scenario("Forecast", "forecast", "fcst"),
        ]
        current = pd.DataFrame(
            [
                ["2026-Q4", "plan", "Comp & Benefits", 10_000_000],
                ["2026-Q4", "fcst", "Comp & Benefits", 12_500_000],
            ],
            columns=["qtr", "version", "cost_element", "value_usd"],
        )
        actuals = pd.DataFrame(
            [["2026-Q3", "Comp & Benefits", 9_000_000]],
            columns=["qtr", "cost_element", "value_usd"],
        )

        walk = build_opex_walk(
            current,
            actuals,
            scenarios,
            "2026-Q4",
            ["2026-Q3"],
        )
        variance = variances(walk, scenarios)

        self.assertAlmostEqual(walk.loc["Comp & Benefits", "2026-Q3"], 9.0)
        self.assertAlmostEqual(walk.loc["Comp & Benefits", "FY26 Plan"], 10.0)
        self.assertAlmostEqual(walk.loc["Comp & Benefits", "Forecast"], 12.5)
        self.assertAlmostEqual(variance.loc["Total", "Forecast vs FY26 Plan"], 2.5)

    def test_headcount_measure_and_per_head_metrics(self):
        hc = pd.DataFrame(
            [
                ["2026-Q4", "fcst", 100, 1],
                ["2026-Q4", "fcst", 120, 2],
                ["2026-Q4", "fcst", 140, 3],
            ],
            columns=["qtr", "version", "headcount", "period"],
        )

        collapsed = collapse_headcount(hc, "2026-Q4", measure="current")
        self.assertEqual(collapsed["fcst"], 120)

        walk = pd.DataFrame({"Forecast": [12.0]}, index=["Comp & Benefits"])
        metrics = per_head_metrics(
            walk,
            pd.Series({"Forecast": 120}),
            ["Comp & Benefits"],
        )
        self.assertAlmostEqual(metrics.loc["Comp & Benefits", "Forecast"], 100.0)


if __name__ == "__main__":
    unittest.main()

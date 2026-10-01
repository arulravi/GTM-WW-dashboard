import json
import pathlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from commentary_store import append_update, materialize_shared_data, read_shared_data


class CommentaryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.shared_dir = pathlib.Path(self.temp_dir.name)
        self.commentary_path = self.shared_dir / "commentary.json"
        self.meta_path = self.shared_dir / "commentary_meta.json"
        self.commentary_path.write_text("{}", encoding="utf-8")
        self.meta_path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_journal_preserves_independent_updates_after_stale_materialization(self):
        original = {
            "l3:Sales Ops L3|__all|2026-Q4": {"Comp & Benefits": "Existing note"},
            "l3:EMEA L3|__all|2026-Q4": {"Outside Labor": "EMEA note"},
        }
        append_update(self.shared_dir, original, kind="baseline")
        append_update(
            self.shared_dir,
            {"l3:Sales Ops L3|__all|2026-Q4": {"Additional Notes": "Sales Ops edit"}},
        )
        append_update(
            self.shared_dir,
            {"l3:EMEA L3|__all|2026-Q4": {"Bonuses": "EMEA edit"}},
        )

        self.commentary_path.write_text(
            json.dumps({"l3:Sales Ops L3|__all|2026-Q4": {"Additional Notes": "Sales Ops edit"}}),
            encoding="utf-8",
        )

        commentary, _ = read_shared_data(self.shared_dir)
        self.assertEqual(
            commentary,
            {
                "l3:Sales Ops L3|__all|2026-Q4": {
                    "Comp & Benefits": "Existing note",
                    "Additional Notes": "Sales Ops edit",
                },
                "l3:EMEA L3|__all|2026-Q4": {
                    "Outside Labor": "EMEA note",
                    "Bonuses": "EMEA edit",
                },
            },
        )

    def test_update_tombstone_does_not_restore_baseline_field(self):
        scope = "l3:Sales Ops L3|__all|2026-Q4"
        append_update(self.shared_dir, {scope: {"Comp & Benefits": "Old note"}}, kind="baseline")
        append_update(self.shared_dir, {scope: {"Comp & Benefits": None}})

        commentary, _ = read_shared_data(self.shared_dir)
        self.assertNotIn(scope, commentary)

    def test_baseline_restores_a_blank_materialized_value(self):
        scope = "l3:Sales Ops L3|__all|2026-Q4"
        self.commentary_path.write_text(
            json.dumps({scope: {"Comp & Benefits": ""}}),
            encoding="utf-8",
        )
        append_update(self.shared_dir, {scope: {"Comp & Benefits": "Saved note"}}, kind="baseline")

        commentary, _ = read_shared_data(self.shared_dir)
        self.assertEqual(commentary[scope]["Comp & Benefits"], "Saved note")

    def test_concurrent_writes_to_separate_l3s_both_survive(self):
        updates = [
            {"l3:Sales Ops L3|__all|2026-Q4": {"Comp & Benefits": "Sales Ops note"}},
            {"l3:EMEA L3|__all|2026-Q4": {"Outside Labor": "EMEA note"}},
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda item: append_update(self.shared_dir, item), updates))

        commentary, _ = materialize_shared_data(self.shared_dir)
        self.assertEqual(
            commentary["l3:Sales Ops L3|__all|2026-Q4"]["Comp & Benefits"],
            "Sales Ops note",
        )
        self.assertEqual(
            commentary["l3:EMEA L3|__all|2026-Q4"]["Outside Labor"],
            "EMEA note",
        )

    def test_materialize_writes_merged_commentary(self):
        append_update(
            self.shared_dir,
            {"l3:Sales Ops L3|__all|2026-Q4": {"Comp & Benefits": "Saved note"}},
        )
        commentary, _ = materialize_shared_data(self.shared_dir)
        stored = json.loads(self.commentary_path.read_text(encoding="utf-8"))
        self.assertEqual(stored, commentary)
        self.assertEqual(stored["l3:Sales Ops L3|__all|2026-Q4"]["Comp & Benefits"], "Saved note")

    def test_invalid_canonical_file_fails_closed(self):
        self.commentary_path.write_text("{", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            read_shared_data(self.shared_dir)


if __name__ == "__main__":
    unittest.main()

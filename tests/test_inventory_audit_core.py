from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inventory_audit_core import InventoryItem, discover_entities, parse_art_asset, read_inventory, report_headers, run_audit, run_s3_audit
import inventory_audit_s3
from inventory_audit_s3 import inventory_report_path, parse_s3_inventory_uri, write_inventory_report


class InventoryAuditCoreTests(unittest.TestCase):
    def test_parse_art_asset_returns_field_and_dimensions(self) -> None:
        self.assertEqual(parse_art_asset("eng_ca_16x9_3840x2160.jpg"), ("ca_16x9", 3840, 2160))
        self.assertEqual(parse_art_asset("title_eng_tt_9x5_1800x1000.png"), ("tt_9x5", 1800, 1000))
        self.assertIsNone(parse_art_asset("movie_hd.mov"))

    def test_movie_audit_uses_largest_art_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            inventory = Path(temp_dir) / "inventory.csv"
            output = Path(temp_dir) / "audit.csv"
            self._write_inventory(
                inventory,
                [
                    "movies/example_movie_1234567890123/feature/example_eng_ca_16x9_1920x1080.jpg",
                    "movies/example_movie_1234567890123/feature/example_eng_ca_16x9_3840x2160.jpg",
                    "movies/example_movie_1234567890123/feature/example_eng_ca_2x3_2000x3000.jpg",
                    "movies/example_movie_1234567890123/feature/example_eng_bg_16x9_3840x2160.jpg",
                    "movies/example_movie_1234567890123/feature/example_eng_tt_9x5_1800x1000.png",
                    "movies/example_movie_1234567890123/feature/example.mov",
                    "movies/example_movie_1234567890123/feature/example_cc_eng.vtt",
                ],
            )

            result = run_audit(inventory, output)
            self.assertEqual(result.entity_count, 1)
            row = result.rows[0]
            self.assertEqual(row["content_type"], "Movie")
            self.assertEqual(row["title"], "example_movie")
            self.assertEqual(row["sku"], "1234567890123")
            self.assertEqual(row["ca_16x9"], "3840x2160")
            self.assertEqual(row["YouTube"], "complete")
            self.assertEqual(row["Amazon"], "incomplete")
            self.assertIn("srt", row["missing_Amazon"])
            self.assertTrue(result.csv_path.exists())
            self.assertTrue(result.xlsx_path.exists())

    def test_endpoint_columns_are_first(self) -> None:
        self.assertEqual(report_headers()[:6], ["Axinom", "Amazon", "Roku", "Frndly", "T+", "YouTube"])

    def test_s3_inventory_uri_normalization_matches_s3_organizer(self) -> None:
        root = parse_s3_inventory_uri("s3://example-bucket")
        self.assertEqual((root.bucket, root.prefix, root.normalized_uri), ("example-bucket", "", "s3://example-bucket/"))

        prefix = parse_s3_inventory_uri("s3://example-bucket//series/county_rescue//")
        self.assertEqual(prefix.bucket, "example-bucket")
        self.assertEqual(prefix.prefix, "series/county_rescue/")
        self.assertEqual(prefix.normalized_uri, "s3://example-bucket/series/county_rescue/")

    def test_write_inventory_report_matches_s3_organizer_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "inventory.csv"
            _inventory_uri, items = self._single_item_inventory(Path(temp_dir) / "source.csv")
            write_inventory_report("s3://gacm-axinom-staging/movies/", items, output)

            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["inventory_uri", "s3://gacm-axinom-staging/movies/"])
            self.assertEqual(rows[2], ["bucket", "key", "size_bytes", "last_modified", "s3_uri"])
            self.assertEqual(rows[3][0], "gacm-axinom-staging")
            self.assertTrue(rows[3][4].startswith("s3://gacm-axinom-staging/"))

    def test_inventory_report_path_matches_s3_organizer_timestamp_style(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = inventory_report_path(Path(temp_dir) / "audit_output_base")
            self.assertEqual(report_path.parent, Path(temp_dir))
            self.assertRegex(report_path.name, r"^Inventory_Audit_inventory_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv$")

    def test_s3_audit_writes_inventory_then_audits_that_file(self) -> None:
        original_list_inventory = inventory_audit_s3.list_inventory_from_s3

        def fake_list_inventory(location, progress_callback=None):
            return [
                InventoryItem(
                    bucket=location.bucket,
                    key="movies/example_movie_1234567890123/feature/example.mov",
                    size_bytes=1000,
                    last_modified="2026-05-15T00:00:00+00:00",
                )
            ]

        inventory_audit_s3.list_inventory_from_s3 = fake_list_inventory
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                progress_messages: list[str] = []
                output = Path(temp_dir) / "s3_audit"
                result = run_s3_audit(
                    "s3://example-bucket/movies/",
                    output,
                    progress_callback=progress_messages.append,
                )

                self.assertTrue(result.inventory_csv_path)
                self.assertTrue(result.inventory_csv_path.exists())
                self.assertTrue(result.csv_path.exists())
                self.assertTrue(result.xlsx_path.exists())
                self.assertEqual(result.source_file_count, 1)
                self.assertIn("Step 1/2: creating raw S3 inventory CSV.", progress_messages)
                self.assertTrue(any(message.startswith("Step 2/2: auditing raw inventory CSV") for message in progress_messages))
        finally:
            inventory_audit_s3.list_inventory_from_s3 = original_list_inventory

    def test_series_inventory_discovers_series_season_and_episode_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            inventory = Path(temp_dir) / "series.csv"
            self._write_inventory(
                inventory,
                [
                    "series/county_rescue_2310526531722/county_rescue_eng_ca_16x9_3840x2160.jpg",
                    "series/county_rescue_2310526531722/s02/county_rescue_s02_eng_ca_16x9_3840x2160.jpg",
                    "series/county_rescue_2310526531722/s02/e03/county_rescue_s02_e03.mov",
                    "series/county_rescue_2310526531722/s02/e03/county_rescue_s02_e03_cc_eng.vtt",
                    "series/county_rescue_2310526531722/s02/e03/county_rescue_s02_e03_eng_bg_16x9_3840x2160.jpg",
                ],
            )

            inventory_uri, items = read_inventory(inventory)
            entities = discover_entities(items, inventory_uri)
            self.assertEqual([entity.content_type for entity in entities], ["Series", "Season", "Episode"])
            self.assertEqual([entity.name for entity in entities], ["county_rescue", "county_rescue_s02", "county_rescue_s02_e03"])

    def _write_inventory(self, path: Path, keys: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["inventory_uri", "s3://gacm-axinom-staging/"])
            writer.writerow([])
            writer.writerow(["bucket", "key", "size_bytes", "last_modified", "s3_uri"])
            for index, key in enumerate(keys, start=1):
                writer.writerow(["gacm-axinom-staging", key, index * 1000, "2026-05-15T00:00:00+00:00", f"s3://gacm-axinom-staging/{key}"])

    def _single_item_inventory(self, path: Path) -> tuple[str, list]:
        self._write_inventory(path, ["movies/example_movie_1234567890123/feature/example.mov"])
        return read_inventory(path)


if __name__ == "__main__":
    unittest.main()

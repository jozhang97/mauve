import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from Bio.Seq import Seq
from Bio.SeqFeature import (BeforePosition, CompoundLocation, FeatureLocation,
                            SeqFeature)
from Bio.SeqRecord import SeqRecord
from Bio import SeqIO


SCRIPT = Path(__file__).parents[2] / "tools" / "normalize_ori.py"
SPEC = importlib.util.spec_from_file_location("normalize_ori", SCRIPT)
normalize_ori = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normalize_ori)


class NormalizeOriTest(unittest.TestCase):
    def record(self):
        record = SeqRecord(Seq("AAAACCCCGGGGTTTT"), id="TEST", name="TEST")
        record.annotations["topology"] = "circular"
        record.annotations["molecule_type"] = "DNA"
        record.features = [
            SeqFeature(FeatureLocation(8, 12), type="rep_origin"),
            SeqFeature(FeatureLocation(6, 10, strand=1), type="CDS"),
            SeqFeature(FeatureLocation(1, 3, strand=-1), type="CDS"),
        ]
        return record

    def test_annotated_origin_rotates_sequence_and_features(self):
        original = self.record()
        feature_sequences = [str(feature.extract(original.seq))
                             for feature in original.features]
        record, report = normalize_ori.normalize_record(original)
        self.assertEqual(str(record.seq), "GGGGTTTTAAAACCCC")
        self.assertEqual((int(record.features[0].location.start),
                          int(record.features[0].location.end)), (0, 4))
        self.assertIsInstance(record.features[1].location, CompoundLocation)
        self.assertEqual(report["original_ori_start_1_based"], 9)
        self.assertTrue(report["rotated"])
        self.assertEqual([str(feature.extract(record.seq))
                          for feature in record.features], feature_sequences)

    def test_linear_record_is_not_modified(self):
        record = self.record()
        record.annotations["topology"] = "linear"
        original = str(record.seq)
        record, report = normalize_ori.normalize_record(record)
        self.assertEqual(str(record.seq), original)
        self.assertEqual(report["reason"], "record is not circular")

    def test_missing_origin_is_kept_by_default(self):
        record = self.record()
        record.features = []
        record, report = normalize_ori.normalize_record(record)
        self.assertFalse(report["rotated"])
        self.assertEqual(report["reason"], "no rep_origin feature")

    def test_genbank_and_embl_round_trip(self):
        for extension, format_name in (("gbk", "genbank"), ("embl", "embl")):
            with self.subTest(format=format_name), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / ("input." + extension)
                output = Path(tmp) / ("output." + extension)
                SeqIO.write([self.record()], source, format_name)
                self.assertEqual(normalize_ori.main([str(source), str(output)]), 0)
                result = SeqIO.read(output, format_name)
                self.assertEqual(str(result.seq), "GGGGTTTTAAAACCCC")
                self.assertEqual(int(result.features[0].location.start), 0)
                report = Path(str(output) + ".ori.json")
                self.assertTrue(report.exists())
                self.assertIn("Mauve ori normalization",
                              str(result.annotations.get("comment", "")))

    def test_doric_lookup_imports_origin_and_rotates(self):
        record = self.record()
        record.features = []
        row = {
            "ori_id": "ORI_TEST",
            "nc": "TEST",
            "seq_size": "16",
            "orics": json.dumps([{
                "oric_start": 9,
                "oric_end": 12,
                "oric_seq": "GGGG",
            }]),
            "evidence_level": "Linked",
            "comparative_support": "Multi-accession",
        }
        normalized, report = normalize_ori.normalize_record(record, [row])
        self.assertEqual(str(normalized.seq), "GGGGTTTTAAAACCCC")
        self.assertEqual(report["method"], "DoriC")
        self.assertEqual(report["doric_id"], "ORI_TEST")
        self.assertEqual(report["original_ori_start_1_based"], 9)
        origin = [feature for feature in normalized.features
                  if feature.type == "rep_origin"]
        self.assertEqual(len(origin), 1)
        self.assertEqual(int(origin[0].location.start), 0)

    def test_doric_csv_cli_fallback(self):
        record = self.record()
        record.features = []
        fields = ["ori_id", "nc", "seq_size", "orics", "evidence_level",
                  "comparative_support"]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.gbk"
            output = Path(tmp) / "output.gbk"
            database = Path(tmp) / "doric.csv"
            SeqIO.write([record], source, "genbank")
            with database.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "ori_id": "ORI_TEST", "nc": "TEST", "seq_size": 16,
                    "orics": json.dumps([{"oric_start": 9, "oric_end": 12,
                                           "oric_seq": "GGGG"}]),
                    "evidence_level": "Not linked",
                    "comparative_support": "Singleton",
                })
            status = normalize_ori.main([
                "--doric-csv", str(database), str(source), str(output)])
            self.assertEqual(status, 0)
            self.assertEqual(str(SeqIO.read(output, "genbank").seq),
                             "GGGGTTTTAAAACCCC")

    def test_fuzzy_positions_survive_rotation(self):
        location = FeatureLocation(BeforePosition(1), 3, strand=1)
        shifted = normalize_ori.shift_location(location, 8, 16)
        self.assertIsInstance(shifted.start, BeforePosition)
        self.assertEqual(int(shifted.start), 9)


if __name__ == "__main__":
    unittest.main()

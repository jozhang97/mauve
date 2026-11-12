#!/usr/bin/env python3
"""Rotate circular bacterial INSDC records so oriC starts at coordinate 1."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from Bio import SeqIO
from Bio.SeqFeature import CompoundLocation, FeatureLocation, SeqFeature


FORMAT_BY_SUFFIX = {
    ".gb": "genbank", ".gbk": "genbank", ".gbff": "genbank",
    ".genbank": "genbank", ".embl": "embl",
}


def infer_format(path):
    try:
        return FORMAT_BY_SUFFIX[path.suffix.lower()]
    except KeyError:
        raise ValueError("cannot infer format from %s; specify it explicitly" % path)


def is_circular(record):
    return str(record.annotations.get("topology", "")).lower() == "circular"


def record_accessions(record):
    values = {str(record.id), str(record.name)}
    values.update(str(value) for value in record.annotations.get("accessions", []))
    return {value for value in values if value and value != "<unknown name>"}


def load_doric_rows(path, records):
    """Load only DoriC rows that could correspond to the input records."""
    exact = set()
    unversioned = set()
    for record in records:
        for accession in record_accessions(record):
            exact.add(accession)
            unversioned.add(accession.split(".")[0])
    matches = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ori_id", "nc", "seq_size", "orics"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("DoriC CSV is missing required columns: %s" %
                             ", ".join(sorted(required)))
        for row in reader:
            accession = row["nc"].strip()
            if accession in exact or accession.split(".")[0] in unversioned:
                matches.append(row)
    return matches


def doric_candidate(record, rows):
    accessions = record_accessions(record)
    exact_rows = [row for row in rows if row["nc"].strip() in accessions]
    if exact_rows:
        matching_rows = exact_rows
    else:
        bases = {accession.split(".")[0] for accession in accessions}
        matching_rows = [row for row in rows
                         if row["nc"].strip().split(".")[0] in bases]

    candidates = {}
    sequence = str(record.seq).upper()
    for row in matching_rows:
        try:
            if int(row["seq_size"]) != len(record):
                continue
            origins = json.loads(row["orics"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for origin in origins:
            try:
                start = int(origin["oric_start"])
                end = int(origin["oric_end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 1 <= start <= end <= len(record):
                continue
            expected = "".join(str(origin.get("oric_seq", "")).split()).upper()
            if expected and sequence[start - 1:end] != expected:
                continue
            key = (start, end)
            candidates[key] = {
                "start": start,
                "end": end,
                "ori_id": row["ori_id"].strip(),
                "nc": row["nc"].strip(),
                "evidence_level": row.get("evidence_level", "").strip(),
                "comparative_support": row.get("comparative_support", "").strip(),
            }
    if len(candidates) == 1:
        return next(iter(candidates.values())), None
    if len(candidates) > 1:
        return None, "multiple DoriC origin candidates"
    return None, "no matching DoriC origin"


def shift_simple_location(location, offset, length):
    start_position, end_position = location.start, location.end
    start, end, strand = int(start_position), int(end_position), location.strand
    if start == 0 and end == length:
        return FeatureLocation(0, length, strand=strand)
    if end <= offset:
        shift = length - offset
        return FeatureLocation(start_position + shift, end_position + shift,
                               strand=strand)
    if start >= offset:
        return FeatureLocation(start_position - offset, end_position - offset,
                               strand=strand)
    left = FeatureLocation(0, end_position - offset, strand=strand)
    right = FeatureLocation(start_position + length - offset, length,
                            strand=strand)
    parts = [right, left] if strand != -1 else [left, right]
    return CompoundLocation(parts, operator="join")


def shift_location(location, offset, length):
    if isinstance(location, CompoundLocation):
        shifted = []
        for part in location.parts:
            result = shift_simple_location(part, offset, length)
            shifted.extend(result.parts if isinstance(result, CompoundLocation)
                           else [result])
        return CompoundLocation(shifted, operator=location.operator)
    return shift_simple_location(location, offset, length)


def rotate_record(record, offset):
    length = len(record)
    if not 0 <= offset < length:
        raise ValueError("rotation offset outside record")
    if offset:
        record.seq = record.seq[offset:] + record.seq[:offset]
        for feature in record.features:
            feature.location = shift_location(feature.location, offset, length)
    return record


def add_provenance(record, provenance):
    message = "Mauve ori normalization: " + json.dumps(provenance, sort_keys=True)
    comments = record.annotations.get("comment", [])
    if isinstance(comments, str):
        comments = [comments]
    record.annotations["comment"] = list(comments) + [message]


def normalize_record(record, doric_rows=None, on_missing="keep"):
    result = {"record_id": record.id, "length": len(record), "rotated": False,
              "original_ori_start_1_based": None}
    if not is_circular(record):
        result.update(status="skipped", reason="record is not circular")
        return record, result
    origins = [f for f in record.features if f.type == "rep_origin"]
    if len(origins) > 1:
        result.update(status="skipped", reason="multiple rep_origin features")
        if on_missing == "error":
            raise ValueError("%s has multiple rep_origin features" % record.id)
        return record, result
    if origins:
        parts = origins[0].location.parts
        offset = int((parts[-1] if parts[0].strand == -1 else parts[0]).start)
        evidence = {"method": "annotated:rep_origin", "confidence": "annotation"}
    elif doric_rows is not None:
        candidate, reason = doric_candidate(record, doric_rows)
        if candidate is None:
            result.update(status="skipped", reason=reason)
            if on_missing == "error":
                raise ValueError("%s: %s" % (record.id, reason))
            return record, result
        offset = candidate["start"] - 1
        evidence = {
            "method": "DoriC",
            "confidence": "DoriC record (not independently validated)",
            "doric_id": candidate["ori_id"],
            "doric_accession": candidate["nc"],
            "doric_ori_start_1_based": candidate["start"],
            "doric_ori_end_1_based_inclusive": candidate["end"],
            "doric_evidence_level": candidate["evidence_level"],
            "doric_comparative_support": candidate["comparative_support"],
        }
        record.features.append(SeqFeature(
            FeatureLocation(offset, candidate["end"]),
            type="rep_origin",
            qualifiers={
                "db_xref": ["DoriC:%s" % candidate["ori_id"]],
                "inference": ["profile:DoriC"],
                "note": ["origin imported from DoriC; computational database record"],
            },
        ))
    else:
        result.update(status="skipped", reason="no rep_origin feature")
        if on_missing == "error":
            raise ValueError("%s has no rep_origin feature" % record.id)
        return record, result
    provenance = dict(evidence)
    provenance.update(original_ori_start_1_based=offset + 1,
                      rotation_offset_bp=offset)
    rotate_record(record, offset)
    add_provenance(record, provenance)
    result.update(provenance)
    result.update(status="normalized", rotated=offset != 0)
    return record, result


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("input", type=Path)
    result.add_argument("output", type=Path)
    result.add_argument("--input-format", choices=("embl", "genbank"))
    result.add_argument("--output-format", choices=("embl", "genbank"))
    result.add_argument("--doric-csv", type=Path,
                        help="DoriC 14 release or filtered CSV used when rep_origin is absent")
    result.add_argument("--on-missing", choices=("keep", "error"), default="keep")
    result.add_argument("--provenance", type=Path,
                        help="JSON report (default: OUTPUT.ori.json)")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        input_format = args.input_format or infer_format(args.input)
        output_format = args.output_format or infer_format(args.output)
        records, report = [], []
        with args.input.open() as input_handle:
            records = list(SeqIO.parse(input_handle, input_format))
        if not records:
            raise ValueError("input contains no sequence records")
        doric_rows = (load_doric_rows(args.doric_csv, records)
                      if args.doric_csv else None)
        normalized_records = []
        for record in records:
            record, item = normalize_record(record, doric_rows, args.on_missing)
            normalized_records.append(record)
            report.append(item)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as output_handle:
            SeqIO.write(normalized_records, output_handle, output_format)
        report_path = args.provenance or Path(str(args.output) + ".ori.json")
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError) as error:
        print("normalize_ori: %s" % error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

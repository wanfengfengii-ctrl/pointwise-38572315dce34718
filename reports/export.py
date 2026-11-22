import json
import sqlite3

from models.codec import encode_fraction, encode_origin
from reports.history import read


def export_report(connection: sqlite3.Connection, report_id: int) -> str:
    report = read(connection, report_id)
    result = report.result
    conditional = result.conditional_cooccurrence
    return json.dumps({
        'version': 1,
        'report_id': report.report_id,
        'accepted_id': result.accepted_id,
        'model_id': result.model_id,
        'origin': encode_origin(result.origin),
        'initial_kind': result.initial_kind,
        'round_number': result.round_number,
        'clearance': encode_fraction(result.clearance),
        'conditional_cooccurrence': None if conditional is None else encode_fraction(conditional),
    }, sort_keys=True, separators=(',', ':'))

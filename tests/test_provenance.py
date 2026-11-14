from pathlib import Path
import hashlib
import json


def test_vendored_algorithm_and_extracted_source_snapshot_hashes():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'PROVENANCE.json').read_text())
    assert len(manifest['records'])>=20
    for row in manifest['records']:
        assert hashlib.sha256((root/row['destination']).read_bytes()).hexdigest()==row['destination_sha256'], row['destination']

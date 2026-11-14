from pathlib import Path
import hashlib
import json
import pytest


def test_vendored_algorithm_and_extracted_source_snapshot_hashes():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'PROVENANCE.json').read_text())
    assert len(manifest['records'])>=20
    for row in manifest['records']:
        assert hashlib.sha256((root/row['destination']).read_bytes()).hexdigest()==row['destination_sha256'], row['destination']


def test_explicit_lf_normalization_still_detects_algorithm_changes(tmp_path):
    from tools.verify_provenance import verify
    source_root = tmp_path / 'original'
    delivery = tmp_path / 'delivery'
    source_root.mkdir()
    delivery.mkdir()
    original = b'from skillopt.types import Edit\r\nBUDGET = 3\r\n'
    normalized = original.replace(b'skillopt.', b'skill_optimizer._vendor.skillopt.').replace(b'\r\n', b'\n')
    (source_root / 'source.py').write_bytes(original)
    (delivery / 'target.py').write_bytes(normalized)
    row = dict(source='source.py', source_sha256=hashlib.sha256(original).hexdigest(),
               destination='target.py', destination_sha256=hashlib.sha256(normalized).hexdigest(),
               mode='namespace_only', normalize_line_endings='lf')
    (delivery / 'PROVENANCE.json').write_text(json.dumps({'records': [row]}), encoding='utf-8')
    assert verify(delivery, source_root)['verified_files'] == 1
    changed = normalized.replace(b'BUDGET = 3', b'BUDGET = 9')
    (delivery / 'target.py').write_bytes(changed)
    # Even updating the delivery hash cannot conceal a change from the source.
    row['destination_sha256'] = hashlib.sha256(changed).hexdigest()
    (delivery / 'PROVENANCE.json').write_text(json.dumps({'records': [row]}), encoding='utf-8')
    with pytest.raises(AssertionError, match='Unexpected algorithm modification'):
        verify(delivery, source_root)

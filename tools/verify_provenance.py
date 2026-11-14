"""Verify vendored/extracted file hashes; optionally verify original source tree."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(root, source_root=None):
    manifest=json.loads((root/'PROVENANCE.json').read_text(encoding='utf-8'))
    count=0
    for row in manifest['records']:
        target=root/row['destination']
        assert hashlib.sha256(target.read_bytes()).hexdigest()==row['destination_sha256'], str(target)
        if source_root:
            source=source_root/row['source']
            assert hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256'], row['source']
            if row['mode']=='namespace_only':
                expected=source.read_bytes().replace(b'from skillopt.',b'from skill_optimizer._vendor.skillopt.').replace(b'from skillopt import',b'from skill_optimizer._vendor.skillopt import')
                assert target.read_bytes()==expected, 'Unexpected algorithm modification: '+row['destination']
            elif row['mode']=='exact_copy':
                assert target.read_bytes()==source.read_bytes(), row['destination']
        count+=1
    return dict(verified_files=count, original_source_checked=source_root is not None)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path);args=ap.parse_args()
    print(json.dumps(verify(Path(__file__).resolve().parents[1],args.source_root)))

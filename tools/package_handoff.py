"""Allowlist-only ZIP, source integrity/sensitive-literal checks and file manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','ARCHITECTURE.zh.md','XIAOYI_WORK_ADAPTATION.zh.md','XIAOYI_WORK_RUNBOOK.zh.md','HANDOFF.zh.md',
     'THIRD_PARTY_NOTICES.md','LICENSE','PROVENANCE.json','pyproject.toml','requirements.txt',
     'requirements-tested.txt','.gitignore','.gitattributes'}
DIRS={'src','configs','examples','tests','tools','licenses','reports','dist'}


def candidates():
    files=[]
    for child in ROOT.iterdir():
        if child.is_file() and child.name in TOP:files.append(child)
        elif child.is_dir() and child.name in DIRS:
            for path in child.rglob('*'):
                parts=path.relative_to(ROOT).parts
                if not path.is_file() or any(p in {'__pycache__','.pytest_cache'} or p.endswith('.egg-info') for p in parts):continue
                if path.name in {'build.txt'} or path.suffix in {'.pyc','.pyo'}:continue
                if child.name=='dist' and path.suffix!='.whl':continue
                if path.is_symlink():raise ValueError('Archive must not follow symlinks')
                files.append(path)
    return sorted(files)


def scan(files):
    for path in files:
        if path.suffix=='.whl':continue
        text=path.read_text(encoding='utf-8')
        # Literal secrets only, not variable names or documented env placeholders.
        patterns=[r'\bsk-[A-Za-z0-9_-]{24,}\b',r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
                  r'https?://[^\s/@:]+:[^\s/@]+@',r'Bearer [A-Za-z0-9_-]{32,}']
        if any(re.search(pattern,text) for pattern in patterns):
            raise ValueError('Potential sensitive literal in '+str(path.relative_to(ROOT)))
        if path.suffix=='.json':
            data=json.loads(text)
            def visit(value):
                if isinstance(value,dict):
                    for key,item in value.items():
                        if key.lower() in {'apikey','api_key','token','password','secret','access_token'} and isinstance(item,str):
                            if item and not item.startswith(('${','YOUR-','[','SYNTHETIC')):
                                raise ValueError('Potential credential field in '+str(path.relative_to(ROOT)))
                        visit(item)
                elif isinstance(value,list):
                    for item in value:visit(item)
            visit(data)
    return True


def main(output):
    files=candidates();scan(files)
    audit=dict(packaging='explicit allowlist',literal_secret_scan_passed=True,
               excluded=['.venv','runs','build','*.egg-info','__pycache__','original datasets','original trajectories','runtime binaries','credential files'],
               synthetic_examples_only=True,original_projects_modified=False)
    (ROOT/'reports/DELIVERY_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
    files=candidates();scan(files)
    manifest={str(path.relative_to(ROOT)):dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size) for path in files}
    manifest_path=ROOT/'FILE_MANIFEST.json'
    manifest_path.write_text(json.dumps(dict(schema=1,files=manifest),indent=2)+'\n')
    files.append(manifest_path)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sorted(files):archive.write(path,ROOT.name+'/'+str(path.relative_to(ROOT)))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,proof in manifest.items():
            assert hashlib.sha256(archive.read(ROOT.name+'/'+name)).hexdigest()==proof['sha256'],name
        assert len(archive.namelist())==len(manifest)+1
    checksum=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(checksum+'  '+output.name+'\n')
    print(json.dumps(dict(archive=str(output),files=len(files),bytes=output.stat().st_size,sha256=checksum)))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT.parent/(ROOT.name+'.zip'));args=ap.parse_args();main(args.output)

"""Portable UTF-8 artifacts, atomic commits and immutable input checks."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def immutable(path, value):
    """Create once; same exact value is a resume, any drift is an error."""
    path = Path(path)
    if path.exists():
        if read(path) != value:
            raise ValueError(f'Immutable inputs changed: {path}; use a new output directory')
    else:
        dump(path, value)


@contextmanager
def exclusive(path):
    """No fcntl or /proc; stale locks require explicit operator inspection."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError(f'Output is locked; inspect its owning process before removing {path}') from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def implementation_digest():
    root = Path(__file__).resolve().parent
    files = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
             if p.is_file() and p.suffix in {'.py', '.md'}}
    return digest(files)

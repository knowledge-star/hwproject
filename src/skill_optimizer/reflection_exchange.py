"""Reflection through files written by a conversation agent; no model API."""
from pathlib import Path
from .adapters.base import PendingExecution
from .storage import digest, immutable, read, sha


class FileExchangeReflectionModel:
    def identity(self):
        return dict(kind='file_reflection', schema=1, transport='conversation_files')

    def __call__(self, system, user, *, exchange_directory, **kwargs):
        folder = Path(exchange_directory)
        request = dict(schema=1, kind='reflection', system=system, user=user,
                       options=kwargs, backend=self.identity())
        immutable(folder / 'request.json', request)
        prompt = '# Reflection instructions\n\n' + system + '\n\n# Input\n\n' + user
        prompt_path = folder / 'PROMPT.md'
        if prompt_path.exists() and prompt_path.read_text(encoding='utf-8') != prompt:
            raise ValueError('Reflection prompt changed after preparation')
        prompt_path.write_text(prompt, encoding='utf-8')
        response_path = folder / 'response.json'
        if not response_path.exists():
            raise PendingExecution(f'Reflection pending: {folder / "request.json"}; submit reply then rerun')
        response = read(response_path)
        if response.get('schema') != 1 or response.get('request_sha256') != sha(folder / 'request.json'):
            raise ValueError('Reflection response not bound to this exact request')
        text, usage = response.get('text'), response.get('usage', {})
        if not isinstance(text, str) or not text.strip() or not isinstance(usage, dict):
            raise ValueError('Reflection needs nonempty reply text and usage object')
        if response.get('response_sha256') != digest(text):
            raise ValueError('Reflection response integrity failure')
        return text, usage


def write_reflection_response(request_path, text, metadata=None):
    """Bind the actual reply to a request; the learner validates its patch later."""
    request_path = Path(request_path)
    request = read(request_path)
    if request.get('schema') != 1 or request.get('kind') != 'reflection':
        raise ValueError('Not a reflection request')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Reflection reply must be nonempty text')
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('Reflection metadata must be an object')
    response = dict(schema=1, request_sha256=sha(request_path), text=text,
                    response_sha256=digest(text), usage={}, metadata=metadata or {})
    path = request_path.with_name('response.json')
    immutable(path, response)
    return path


def exchange_status(output):
    """List unconsumed public task/reflection requests, without reading gold data."""
    output = Path(output).resolve()
    rows = []
    for path in sorted(output.glob('**/exchange/request.json')):
        request = read(path)
        reflection = request.get('kind') == 'reflection'
        # Task exchange is below the task folder; reflection exchange below cache key.
        committed = path.parent.parent / ('complete.json' if reflection else 'execution.json')
        if committed.exists():
            continue
        row = dict(kind='reflection' if reflection else 'execution', request=str(path),
                   request_sha256=sha(path),
                   state='response_supplied' if path.with_name('response.json').exists() else 'awaiting_response')
        if reflection:
            row['prompt'] = str(path.with_name('PROMPT.md'))
        else:
            row.update(task_id=request['task']['id'], split=request['task']['split'],
                       skill=str(path.with_name('SKILL.md')), skill_sha256=request['skill_sha256'])
        rows.append(row)
    return dict(final_exists=(output / 'final/freeze.json').exists(), requests=rows)

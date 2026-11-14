"""Reflection I/O only. The algorithm is in the vendored dispatcher."""
from pathlib import Path
import json
import os
import threading
import urllib.request
from .storage import canonical, digest, dump, immutable, read
from .adapters.base import PendingExecution
from .reflection_exchange import FileExchangeReflectionModel


class CachedModel:
    """Exact full-input cache; ambiguous inference never silently reissued."""
    def __init__(self, model, directory):
        self.model, self.directory = model, Path(directory)
        self.lock = threading.Lock()
        self.call_locks = {}
        self.pending = []

    def __call__(self, system, user, **kwargs):
        request = dict(system=system, user=user, options=kwargs, backend=self.model.identity())
        key = digest(request)
        with self.lock:
            lock = self.call_locks.setdefault(key, threading.Lock())
        with lock:
            folder = self.directory / key
            immutable(folder / 'input.json', request)
            result = folder / 'complete.json'
            if result.exists():
                data = read(result)
                if data['input_sha256'] != key or data['response_sha256'] != digest(data['text']):
                    raise ValueError('Reflection cache integrity failure')
                return data['text'], data['usage']
            if isinstance(self.model, FileExchangeReflectionModel):
                # Preparing a file request is repeatable, and is not an ambiguous API call.
                try:
                    text, usage = self.model(system=system, user=user,
                                             exchange_directory=folder / 'exchange', **kwargs)
                except PendingExecution as exc:
                    with self.lock:
                        self.pending.append(str(exc))
                    raise
            else:
                marker = folder / 'started.json'
                if marker.exists():
                    raise RuntimeError(f'Unresolved reflection; inspect {folder}; no automatic retry')
                dump(marker, dict(input_sha256=key))
                # Ambiguous remote calls are never automatically reissued.
                text, usage = self.model(system=system, user=user, **kwargs)
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Empty reflection response; retained unresolved call')
            dump(result, dict(input_sha256=key, text=text, usage=usage, response_sha256=digest(text)))
            return text, usage


class SyntheticReflectionModel:
    """Canned synthetic response. No LLM; only an integration test fixture."""
    def identity(self):
        return dict(kind='synthetic_fixture', version=1, real_inference=False)

    def __call__(self, system, user, **kwargs):
        card = dict(title='Calculate and check totals', trigger=['total', 'sum', '合计'],
                    body='For a requested total, add all provided operands using a calculation tool. Inspect the tool result and return only the requested value. Do not use this procedure for a ratio or an average.',
                    required_operations=['sum'])
        return json.dumps(dict(patch=dict(reasoning='Synthetic fixture; no model inference.',
                           edits=[dict(op='append', content=json.dumps(card))]))), {}


class OpenAICompatibleModel:
    """Explicit opt-in to a caller-supplied endpoint. No credential file reads."""
    def __init__(self, base_url, model, api_key_env='SKILL_OPTIMIZER_API_KEY', temperature=0,
                 timeout=360, max_tokens=16384):
        self.base_url, self.model, self.api_key_env = base_url.rstrip('/'), model, api_key_env
        self.temperature, self.timeout, self.max_tokens = temperature, timeout, max_tokens

    def identity(self):
        return dict(kind='openai_compatible', base_url=self.base_url, model=self.model,
                    api_key_env=self.api_key_env, temperature=self.temperature,
                    timeout=self.timeout, max_tokens=self.max_tokens)

    def __call__(self, system, user, max_completion_tokens=16384, **kwargs):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f'Set environment variable {self.api_key_env}; never put credentials in config')
        payload = dict(model=self.model, messages=[dict(role='system', content=system),
                       dict(role='user', content=user)], temperature=self.temperature,
                       stream=False, max_tokens=min(max_completion_tokens, self.max_tokens))
        request = urllib.request.Request(self.base_url + '/chat/completions',
                  data=canonical(payload).encode(), headers={'Content-Type': 'application/json',
                  'Authorization': 'Bearer ' + key}, method='POST')
        # Exceptions are deliberately short and exclude headers/provider bodies.
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except Exception as exc:
            raise RuntimeError(f'Optimizer transport failed ({type(exc).__name__}); inspect unresolved call') from None
        return result['choices'][0]['message']['content'], result.get('usage', {})

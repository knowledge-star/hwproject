"""File/script interchange. Works without a programmable target runtime API."""
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
from .base import PendingExecution, SkillExportMixin
from ..contracts import Execution
from ..storage import digest, dump, immutable, read, sha


class FileExchangeAdapter(SkillExportMixin):
    def identity(self):
        return dict(kind='file_exchange', schema=1, real_runtime_verified=False)

    def prepare(self, task, skill, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        skill_hash = digest(skill)
        skill_path = directory / 'SKILL.md'
        if skill_path.exists() and skill_path.read_text(encoding='utf-8') != skill:
            raise ValueError('Request Skill drift')
        self.export_skill(skill, skill_path)
        request = dict(schema=1, task=task, skill_file='SKILL.md', skill_sha256=sha(skill_path),
                       skill_text_digest=skill_hash, adapter=self.identity())
        immutable(directory / 'request.json', request)
        return request

    def receive(self, task, directory):
        directory = Path(directory)
        response_path = directory / 'response.json'
        if not response_path.exists():
            raise PendingExecution(f'Request pending: {directory / "request.json"}; supply response.json then rerun')
        request = read(directory / 'request.json')
        if sha(directory / 'SKILL.md') != request['skill_sha256']:
            raise ValueError('Exchange Skill changed after submission')
        response = read(response_path)
        if response.get('schema') != 1 or response.get('request_sha256') != sha(directory / 'request.json'):
            raise ValueError('Response not bound to this exact request')
        result = Execution(**response['execution']).validate(task)
        if response.get('judge_feedback') is not None:
            result.metadata['judge_feedback'] = response['judge_feedback']
        result.metadata['exchange_request_sha256'] = sha(directory / 'request.json')
        return result

    def execute(self, task, skill, directory):
        self.prepare(task, skill, directory)
        return self.receive(task, directory)


class CommandAdapter(FileExchangeAdapter):
    """Caller-owned process implements the same request/response JSON contract."""
    def __init__(self, command, timeout=1800):
        if not command or not isinstance(command, list):
            raise ValueError('command must be a nonempty argv list')
        self.command, self.timeout = command, timeout

    def identity(self):
        return dict(kind='command', schema=1, command=self.command, timeout=self.timeout)

    def execute(self, task, skill, directory):
        self.prepare(task, skill, directory)
        directory = Path(directory).resolve()
        if not (directory / 'response.json').exists():
            if (directory / 'started.json').exists():
                raise PendingExecution(f'Script call unresolved: {directory}; inspect before any retry')
            dump(directory / 'started.json', dict(request_sha256=sha(directory / 'request.json')))
            values = dict(request=str(directory / 'request.json'), response=str(directory / 'response.json'),
                          python=sys.executable, directory=str(directory))
            command = [part.format(**values) for part in self.command]
            try:
                result = subprocess.run(command, cwd=directory, capture_output=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                raise PendingExecution(f'Script timed out: {directory}; no automatic retry') from None
            # Do not dump command stdout/stderr: caller scripts may log credentials.
            dump(directory / 'exit.json', dict(returncode=result.returncode))
            if result.returncode:
                raise RuntimeError(f'Harness script failed with code {result.returncode}; inspect its own logs')
        return self.receive(task, directory)


def write_response(request_path, execution, response_path=None, judge_feedback=None):
    request_path = Path(request_path)
    request = read(request_path)
    execution.validate(request['task'])
    response = dict(schema=1, request_sha256=sha(request_path), execution=asdict(execution))
    if judge_feedback is not None:
        response['judge_feedback'] = judge_feedback
    response_path = Path(response_path) if response_path else request_path.with_name('response.json')
    immutable(response_path, response)
    return response_path

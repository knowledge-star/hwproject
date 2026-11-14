"""Portable native CLI adapter, derived from oqs/container_entry.py + episode.py.

Uses the existing Python subprocess/JSONL interface rather than an invented
OpenClaw API. Model transport and native settings are provided by the caller.
The runtime is not bundled. Existing research state/config is never changed.
"""
from pathlib import Path
import copy
import json
import os
import re
import subprocess
import tempfile
import uuid
from .base import SkillExportMixin
from .ledger import request_ledger
from ..contracts import Execution
from ..storage import digest, dump, read


class OpenClawAdapter(SkillExportMixin):
    def __init__(self, command=None, native_config=None, timeout=1800, provider="experiment"):
        self.provider = provider
        self.command = command or ['openclaw']
        self.native_config = copy.deepcopy(native_config or {})
        self.timeout = timeout

    def identity(self):
        # Configuration may contain ${ENV_NAME} references, never resolved secrets.
        return dict(kind='openclaw_native_cli', command=self.command, timeout=self.timeout,
                    native_config_sha256=digest(self.native_config), trace='native_jsonl',
                    provider=self.provider, request_measure='local HTTP ledger')

    def _run(self, args, env, timeout=120):
        try:
            return subprocess.run(self.command + args, env=env, capture_output=True,
                                  text=True, encoding='utf-8', timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError('OpenClaw CLI unavailable; configure adapter.command with node and openclaw.mjs') from None

    def _config(self, state, workspace, skill_name):
        cfg = copy.deepcopy(self.native_config)
        cfg.setdefault('agents', {}).setdefault('defaults', {}).update(workspace=str(workspace))
        cfg.setdefault('skills', {})['allowBundled'] = []
        cfg['skills'].setdefault('entries', {})
        # Native config supports ${ENV_VAR}; leave placeholders intact. OpenClaw
        # reads its own explicit environment, not this user's credential files.
        path = state / 'openclaw.json'
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        path.chmod(0o600)
        return cfg, path

    def _discover(self, env, cfg, config_path, name):
        p = self._run(['skills', 'list', '--json'], env)
        if p.returncode:
            raise RuntimeError('OpenClaw offline skill discovery failed; verify runtime version/native_config')
        skills = json.loads(p.stdout)['skills']
        for skill in skills:
            cfg['skills']['entries'][skill['name']] = {'enabled': skill['name'] == name}
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        p = self._run(['skills', 'list', '--json'], env)
        if p.returncode:
            raise RuntimeError('OpenClaw skill discovery failed after skill isolation')
        skills = json.loads(p.stdout)['skills']
        active = [s['name'] for s in skills if s.get('eligible') and not s.get('disabled')]
        if sorted(active) != [name]:
            raise RuntimeError(f'OpenClaw skill isolation failed: active={active}')
        return dict(passed=True, active_skills=active)

    def _workspace(self, root, skill):
        workspace = root / 'workspace'
        workspace.mkdir()
        match = re.search(r'^name:\s*([a-z0-9-]+)\s*$', skill, re.M)
        if not match:
            raise ValueError('OpenClaw Skill requires a plain lowercase YAML name')
        name = match[1]
        self.export_skill(skill, workspace / 'skills' / name / 'SKILL.md')
        state = root / '.openclaw'
        state.mkdir()
        cfg, config_path = self._config(state, workspace, name)
        env = dict(os.environ)
        # All native state/auth/session paths are private to this invocation.
        env.update(HOME=str(root), USERPROFILE=str(root), OPENCLAW_HOME=str(root),
                   OPENCLAW_STATE_DIR=str(state), OPENCLAW_CONFIG_PATH=str(config_path),
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        return workspace, state, cfg, config_path, env, name

    def probe(self, skill, directory):
        """Real CLI discovery, no agent invocation or model calls."""
        with tempfile.TemporaryDirectory(prefix='skillopt-openclaw-') as tmp:
            workspace, state, cfg, config_path, env, name = self._workspace(Path(tmp), skill)
            version = self._run(['--version'], env)
            if version.returncode:
                raise RuntimeError('OpenClaw version probe failed')
            audit = self._discover(env, cfg, config_path, name)
            audit.update(version=version.stdout.strip(), model_calls=0, real_agent_execution=False)
            dump(Path(directory) / 'openclaw-probe.json', audit)
            return audit

    def execute(self, task, skill, directory):
        directory = Path(directory)
        # A one-shot marker survives interruption; pipeline will not silently
        # repeat a potentially paid native run whose final result was not committed.
        marker = directory / 'native-started.json'
        if marker.exists():
            raise RuntimeError(f'Unresolved native run: {directory}; inspect before rerunning')
        dump(marker, dict(task_id=task['id'], skill_digest=digest(skill)))
        with tempfile.TemporaryDirectory(prefix='skillopt-openclaw-') as tmp:
            workspace, state, cfg, config_path, env, name = self._workspace(Path(tmp), skill)
            audit = self._discover(env, cfg, config_path, name)
            dump(directory / 'skill-audit.json', audit)
            prompt = f'Use the {name} skill for this task. Read {workspace / "skills" / name / "SKILL.md"} before solving.\n\n' + task['prompt']
            provider = cfg.get('models', {}).get('providers', {}).get(self.provider)
            if not provider:
                raise ValueError('Configure an explicit OpenAI-compatible native provider for exact request accounting')
            # Keys are resolved only for this explicit live execution, never probes.
            key = provider.get('apiKey', '')
            match = re.fullmatch(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', key)
            if not match:
                raise ValueError('Native provider apiKey must be an environment reference ${ENV_NAME}')
            key = os.environ.get(match[1])
            if not key:
                raise RuntimeError('Missing environment variable for native provider authentication')
            with request_ledger(provider['baseUrl'], key) as ledger:
                provider.update(baseUrl=ledger['endpoint'], apiKey=ledger['marker'])
                config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
                try:
                    p = self._run(['agent', '--local', '--agent', 'main', '--session-id', uuid.uuid4().hex,
                                   '--json', '-m', prompt, '--timeout', str(self.timeout)], env, self.timeout + 45)
                except subprocess.TimeoutExpired:
                    p = None
            dump(directory / 'request-ledger.json', ledger['records'])
            rows = []
            for path in sorted((state / 'agents/main/sessions').glob('*.jsonl')):
                if path.name.endswith('.trajectory.jsonl'):
                    continue
                for line in path.read_text(encoding='utf-8').splitlines():
                    row = json.loads(line)
                    if row.get('message'):
                        rows.append(row)
            dump(directory / 'native-conversation.json', rows)
            dump(directory / 'native-exit.json', dict(returncode=None if p is None else p.returncode, timeout=p is None))
            if p is None:
                raise RuntimeError('Native timeout; partial trace retained, no automatic retry')
            if p.returncode:
                raise RuntimeError('Native execution failed; trace retained, no automatic retry. Check runtime/provider configuration.')
            obj = json.loads(p.stdout)
            final = '\n'.join(payload['text'] for payload in obj.get('payloads', []) if payload.get('text'))
            requests = len(ledger['records'])
            if not requests or any(r['status'] != 'complete' for r in ledger['records']):
                dump(directory / 'native-conversation.json', rows)
                raise RuntimeError('Incomplete native provider ledger; preserved evidence, no automatic retry')
            result = Execution(task['id'], final, rows, api_requests=requests,
                               metadata=dict(skill_audit=audit, api_requests_estimated=False,
                                             request_measure='exact local HTTP POST ledger',
                                             runtime_isolation='private state; local CLI is not a sandbox'))
            return result.validate(task)

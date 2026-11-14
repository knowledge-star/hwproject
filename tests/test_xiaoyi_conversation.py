"""Offline fixtures for conversation-file transport, not live Xiaoyi evidence."""
from pathlib import Path
import json
import subprocess
import sys
import pytest
from skill_optimizer import Execution
from skill_optimizer.adapters.base import PendingExecution
from skill_optimizer.adapters.exchange import write_response
from skill_optimizer.cli import load_config, main
from skill_optimizer.models import CachedModel, SyntheticReflectionModel
from skill_optimizer.reflection_exchange import (
    FileExchangeReflectionModel, exchange_status, write_reflection_response,
)
from skill_optimizer.storage import dump, read, sha

ROOT = Path(__file__).resolve().parents[1]


def test_reflection_wait_resume_binding_and_cache(tmp_path):
    model = FileExchangeReflectionModel()
    cached = CachedModel(model, tmp_path)
    with pytest.raises(PendingExecution):
        cached('Instructions', 'Train evidence', stage='analyst')
    request = next(tmp_path.glob('*/exchange/request.json'))
    original_hash = sha(request)
    with pytest.raises(PendingExecution):
        CachedModel(model, tmp_path)('Instructions', 'Train evidence', stage='analyst')
    assert sha(request) == original_hash
    assert not list(tmp_path.glob('*/started.json'))
    text = '{"patch":{"edits":[]}}'
    write_reflection_response(request, text, {'target_session_id': 'fixture-reflector'})
    assert CachedModel(model, tmp_path)('Instructions', 'Train evidence', stage='analyst') == (text, {})
    assert list(tmp_path.glob('*/complete.json'))
    with pytest.raises(ValueError, match='Immutable'):
        write_reflection_response(request, 'changed')


def test_reflection_response_cannot_cross_requests(tmp_path):
    model = FileExchangeReflectionModel()
    for name in ('a', 'b'):
        with pytest.raises(PendingExecution):
            model('Instructions', name, exchange_directory=tmp_path / name)
    path = write_reflection_response(tmp_path / 'a/request.json', '{"patch":{"edits":[]}}')
    dump(tmp_path / 'b/response.json', read(path))
    with pytest.raises(ValueError, match='bound'):
        model('Instructions', 'b', exchange_directory=tmp_path / 'b')
    response = read(path)
    response['text'] = 'tampered'
    dump(path, response)
    with pytest.raises(ValueError, match='integrity'):
        model('Instructions', 'a', exchange_directory=tmp_path / 'a')


@pytest.mark.parametrize('workers', [1, 2])
def test_xiaoyi_six_executions_and_two_reflections_resume(tmp_path, workers):
    """Fresh controller each time; mixed Train batches, fixed Val and unknown counts."""
    rounds = 0
    executed = []
    reflection_inputs = []
    output = tmp_path / 'pilot'
    for _ in range(12):
        cfg, tasks, seed, opt = load_config(ROOT / 'configs/xiaoyi-work.json')
        from dataclasses import replace
        opt.learning = replace(opt.learning, workers=workers)
        try:
            final = opt.run([t for t in tasks if t.split == 'train'],
                            [t for t in tasks if t.split == 'val'], seed, output,
                            selection_policy=cfg['selection_policy'])
            break
        except PendingExecution:
            rounds += 1
            assert not (output / 'run.lock').exists()
            status = exchange_status(output)
            assert status['requests']
            for row in status['requests']:
                path = Path(row['request'])
                req = read(path)
                assert row['state'] == 'awaiting_response'
                if row['kind'] == 'execution':
                    assert 'answer' not in req['task'] and 'reference_text' not in req['task']
                    task = req['task']
                    # Deliberately wrong fixture for one Train item to test failure reflection.
                    answer = '0' if task['id'] == 'train-total-a' else str(sum(task['metadata']['numbers']))
                    result = Execution(task['id'], answer, [dict(role='assistant', content=answer)],
                                       metadata={'evidence_source': 'offline test fixture'})
                    write_response(path, result)
                    assert any(item['request'] == row['request'] and item['state'] == 'response_supplied'
                               for item in exchange_status(output)['requests'])
                    executed.append((str(path), sha(path.with_name('response.json'))))
                else:
                    reflection_inputs.append(req['user'])
                    text, _ = SyntheticReflectionModel()(req['system'], req['user'])
                    reply = path.parent / 'fixture-reply.txt'
                    reply.write_text(text, encoding='utf-8')
                    assert main(['submit-reflection', '--request', str(path), '--reply', str(reply)]) == 0
    else:
        pytest.fail('Conversation loop did not finish')
    assert rounds >= 3 and final.is_file()
    assert len(executed) == 6
    assert len(reflection_inputs) == 2
    assert all('val-total-' not in text for text in reflection_inputs)
    assert not list(output.glob('**/optimizer/*/started.json'))
    assert len(list(output.glob('**/optimizer/*/complete.json'))) == 2
    selection = read(output / 'selection.json')
    assert selection['policy'] == 'webshop'
    assert selection['winner'] == 'seed'  # Both candidates pass; shorter seed wins.
    assert all(row['mean_requests'] is None for row in selection['ranking'])
    assert exchange_status(output) == {'final_exists': True, 'requests': []}
    before = {str(p): sha(p) for p in output.rglob('response.json')}
    opt.run([t for t in tasks if t.split == 'train'], [t for t in tasks if t.split == 'val'],
            seed, output, selection_policy=cfg['selection_policy'])
    assert before == {str(p): sha(p) for p in output.rglob('response.json')}


def test_pending_cli_and_legal_empty_patch(tmp_path, capsys):
    cfg, tasks, seed, opt = load_config(ROOT / 'configs/xiaoyi-work.json')
    train, val = [t for t in tasks if t.split == 'train'], [t for t in tasks if t.split == 'val']
    for _ in train:
        with pytest.raises(PendingExecution):
            opt.run(train, val, seed, tmp_path, selection_policy=cfg['selection_policy'])
        row = exchange_status(tmp_path)['requests'][0]
        task = read(row['request'])['task']
        answer = str(sum(task['metadata']['numbers']))
        write_response(row['request'], Execution(task['id'], answer, [dict(role='assistant', content=answer)]))
    assert main(['run', '--config', str(ROOT / 'configs/xiaoyi-work.json'), '--output', str(tmp_path)]) == 3
    capsys.readouterr()
    assert main(['pending', '--output', str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    row = status['requests'][0]
    assert row['kind'] == 'reflection'
    reply = tmp_path / 'actual-reply.txt'
    reply.write_text('{"patch":{"reasoning":"No additional rule needed","edits":[]}}', encoding='utf-8')
    assert main(['submit-reflection', '--request', row['request'], '--reply', str(reply)]) == 0
    with pytest.raises(PendingExecution):  # Advances to Val, not an unresolved-reflection error.
        opt.run(train, val, seed, tmp_path, selection_policy=cfg['selection_policy'])
    assert read(tmp_path / 'round-001/learning/bank.json')['cards'] == []


def test_complete_request_preserves_session_and_evidence_hashes(tmp_path):
    from skill_optimizer.adapters.xiaoyi import XiaoyiWorkAdapter
    public = dict(id='example', prompt='Return a total.', split='train', metadata={})
    adapter = XiaoyiWorkAdapter()
    with pytest.raises(PendingExecution):
        adapter.execute(public, 'Current Skill', tmp_path / 'exchange')
    trace, final, metadata = [tmp_path / name for name in ('trace.json', 'final.txt', 'metadata.json')]
    dump(trace, [dict(role='assistant', content='5')])
    final.write_text('5', encoding='utf-8')
    dump(metadata, dict(target_session_id='offline-fixture-session', trace_complete=False))
    request = tmp_path / 'exchange/request.json'
    subprocess.run([sys.executable, str(ROOT / 'examples/complete_request.py'),
                    '--request', str(request), '--trace', str(trace), '--final', str(final),
                    '--metadata', str(metadata)], check=True, capture_output=True)
    execution = adapter.execute(public, 'Current Skill', request.parent)
    assert execution.api_requests is None
    assert execution.metadata['target_session_id'] == 'offline-fixture-session'
    assert execution.metadata['trace_complete'] is False
    assert execution.metadata['trace_file_sha256'] == sha(trace)
    assert execution.metadata['final_file_sha256'] == sha(final)
    assert execution.metadata['requested_skill_sha256'] == sha(request.parent / 'SKILL.md')

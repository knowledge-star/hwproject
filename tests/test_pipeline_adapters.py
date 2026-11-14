from dataclasses import asdict
from pathlib import Path
import json
import subprocess
import sys
import pytest
from skill_optimizer import Task, Execution, Score
from skill_optimizer.adapters.exchange import FileExchangeAdapter, CommandAdapter, write_response
from skill_optimizer.adapters.xiaoyi import XiaoyiWorkAdapter
from skill_optimizer.adapters.base import PendingExecution
from skill_optimizer.cli import load_config
from skill_optimizer.judges import ExternalFeedbackJudge
from skill_optimizer.models import CachedModel, SyntheticReflectionModel
from skill_optimizer.storage import dump, read, sha

ROOT = Path(__file__).resolve().parents[1]


def test_complete_real_algorithm_synthetic_runtime_and_resume(tmp_path):
    _, tasks, seed, opt = load_config(ROOT/'configs/mock.json')
    train, val = [t for t in tasks if t.split=='train'], [t for t in tasks if t.split=='val']
    final = opt.run(train,val,seed,tmp_path)
    assert final.is_file()
    selection = read(tmp_path/'selection.json')
    assert selection['winner']=='round-001'
    stats = {r['name']:r['successes'] for r in selection['ranking']}
    assert stats=={'round-001':2,'seed':0}
    calls = list(tmp_path.glob('round-*/learning/optimizer/*/complete.json'))
    assert len(calls)==1
    original = {str(p):sha(p) for p in calls}
    opt.run(train,val,seed,tmp_path)
    assert original == {str(p):sha(p) for p in calls}
    assert 'add all provided operands' in final.read_text()
    assert read(tmp_path/'final/freeze.json')['test_used_for_selection'] is False


def test_two_round_append_chain_deduplicates(tmp_path):
    _, tasks, seed, opt = load_config(ROOT/'configs/mock.json')
    opt.run([t for t in tasks if t.split=='train'],[t for t in tasks if t.split=='val'],seed,tmp_path,rounds=2)
    assert len(read(tmp_path/'round-002/learning/bank.json')['cards'])==1
    assert read(tmp_path/'round-002/learning/raw-patches.json')[0]['source_type']=='success'


def test_exchange_pause_resume_binding_and_private_answer_exclusion(tmp_path):
    adapter = XiaoyiWorkAdapter()
    task = Task('a','Public total task','train',answer='HOST_PRIVATE_GOLD',reference_text='HOST_PRIVATE_REFERENCE')
    with pytest.raises(PendingExecution):adapter.execute(task.public(),'skill',tmp_path)
    raw = (tmp_path/'request.json').read_text()
    assert 'HOST_PRIVATE' not in raw
    assert read(tmp_path/'request.json')['adapter']['api_verified'] is False
    execution = Execution('a','5',[dict(role='assistant',content='5')])
    write_response(tmp_path/'request.json',execution)
    assert adapter.execute(task.public(),'skill',tmp_path).final_answer=='5'
    row=read(tmp_path/'response.json');row['request_sha256']='wrong';dump(tmp_path/'response.json',row)
    with pytest.raises(ValueError,match='bound'):adapter.execute(task.public(),'skill',tmp_path)


def test_file_exchange_pipeline_manual_completion_and_resume(tmp_path):
    _, tasks, seed, opt=load_config(ROOT/'configs/file-exchange.json')
    train, val=[t for t in tasks if t.split=='train'],[t for t in tasks if t.split=='val']
    from skill_optimizer.adapters.synthetic import SyntheticHarness
    for _ in range(12):
        try:
            result=opt.run(train,val,seed,tmp_path)
            break
        except PendingExecution:
            for request_path in tmp_path.glob('**/exchange/request.json'):
                if request_path.with_name('response.json').exists():continue
                req=read(request_path);skill=request_path.with_name('SKILL.md').read_text()
                execution=SyntheticHarness().execute(req['task'],skill,request_path.parent)
                write_response(request_path,execution)
    else:pytest.fail('Did not complete exchange loop')
    assert result.exists() and read(tmp_path/'selection.json')['winner']=='round-001'


def test_real_subprocess_exchange_worker(tmp_path):
    _,tasks,seed,opt=load_config(ROOT/'configs/script.json')
    result=opt.run([t for t in tasks if t.split=='train'],[t for t in tasks if t.split=='val'],seed,tmp_path)
    assert result.exists() and list(tmp_path.glob('**/exchange/response.json'))


def test_unresolved_model_never_resampled_and_cache_binds_boundary(tmp_path):
    class Broken:
        calls=0
        def identity(self):return {'kind':'broken'}
        def __call__(self,**kwargs):
            self.calls+=1
            raise RuntimeError('lost response')
    model=Broken();cached=CachedModel(model,tmp_path)
    with pytest.raises(RuntimeError):cached('a','b\nc')
    with pytest.raises(RuntimeError,match='Unresolved'):cached('a','b\nc')
    assert model.calls==1
    # Different system/user boundaries cannot collide, even with same concatenation.
    with pytest.raises(RuntimeError):cached('a\nb','c')
    assert model.calls==2


def test_external_feedback_qualification():
    task=Task('a','Public task','val')
    judge=ExternalFeedbackJudge()
    execution=Execution('a','x',[dict(role='assistant',content='x')])
    with pytest.raises(ValueError):judge.score(task,execution)
    execution.metadata['judge_feedback']=dict(hard=0,soft=.5,feedback='Missing evidence',qualified=True)
    assert judge.score(task,execution).soft==.5
    execution.status='infrastructure_failure'
    with pytest.raises(ValueError,match='Infrastructure'):judge.score(task,execution)


def test_task_path_and_split_guards(tmp_path):
    for tid in ['../escape','a/b','..','a\\b']:
        with pytest.raises(ValueError):Task(tid,'Prompt','train')
    with pytest.raises(ValueError):Score(0,float('nan'),'bad')
    with pytest.raises(ValueError):Execution('a','',[]).validate({'id':'a'})

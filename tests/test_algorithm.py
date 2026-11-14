from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import pytest
from skill_optimizer import Task, Execution, Score, Experience, LearningConfig, learn, render_bank, select_candidate
from skill_optimizer.models import SyntheticReflectionModel
from skill_optimizer.storage import read
from skill_optimizer.research.officeqa import AuditedReflectionParser, ReflectionRecoveryError, flatten_native, sanitize_card
from skill_optimizer.research.binary import reflection_native
from skill_optimizer._vendor.skillopt.gradient.reflect import fmt_trajectory
from skill_optimizer._vendor.skillopt.optimizer.skill import apply_patch_with_report
from skill_optimizer._vendor.skillopt.evaluation.gate import evaluate_gate


def bank(cards=None):
    return dict(version='seed', base_skill='Base guidance.', cards=cards or [],
                config=dict(routing='topk', topk=1, contract=False))


def card(id='rule', trigger=None, body='Check operands before adding.'):
    return dict(id=id, title='Check operands', trigger=trigger or ['total'], body=body, provenance=[])


def experience(id='a', hard=0, split='train', qualified=True, status='complete'):
    task = Task(id, 'Return the total of 2 and 3.', split, answer='5')
    execution = Execution(id, '2', [dict(role='user',content=task.prompt), dict(type='tool_call',cmd='sum',obs='2')], status=status)
    return Experience(task, execution, Score(hard, hard, 'Synthetic host feedback', qualified))


class FixtureModel:
    def __init__(self, edits):
        self.edits, self.calls = edits, []

    def identity(self):
        return dict(kind='test', edits=self.edits)

    def __call__(self, system, user, **kwargs):
        self.calls.append((system, user))
        return json.dumps(dict(patch=dict(edits=self.edits))), {}


def edit(body='Check operands before adding.'):
    c = dict(title='Check operands', trigger=['total'], body=body, required_operations=['sum'])
    return dict(op='append', content=json.dumps(c))


def test_real_dispatcher_card_update_dedup_and_exact_resume(tmp_path):
    model = FixtureModel([edit()])
    # One failure batch and one success batch produce the same card.
    source = [experience('failure'), experience('success', hard=1)]
    cfg = LearningConfig(workers=2)
    path = learn(source, bank(), tmp_path/'learning', model, 'Train only.', cfg)
    result = read(path)
    assert len(model.calls) == 2
    assert len(result['cards']) == 1
    audit = read(path.parent/'learning-audit.json')
    assert any(d.get('reason') == 'duplicate' for d in audit['decisions'])
    assert {p['source_type'] for p in read(path.parent/'raw-patches.json')} == {'failure','success'}
    assert any('Failed Trajectories' in u for _,u in model.calls)
    assert any('Successful Trajectories' in u for _,u in model.calls)
    learn(source, bank(), tmp_path/'learning', model, 'Train only.', cfg)
    assert len(model.calls) == 2
    changed = [experience('failure'), experience('success', hard=0)]
    with pytest.raises(ValueError, match='Immutable'):
        learn(changed, bank(), tmp_path/'learning', model, 'Train only.', cfg)


def test_seed_preservation_filters_and_legal_zero_edits(tmp_path):
    initial = bank([card('seed',body='Preserve this prior rule.')])
    model = FixtureModel([edit('Use treasury_bulletin UID123 and values from 2025.'), edit()])
    path = learn([experience()], initial, tmp_path/'one', model, 'Prompt', LearningConfig(workers=1))
    result = read(path)
    assert initial['cards'][0] == result['cards'][0]
    assert len(result['cards']) == 2
    assert read(path.parent/'learning-audit.json')['decisions'][0]['reason'] == 'task_specific_identifier_or_value'
    empty = FixtureModel([])
    path = learn([experience()], initial, tmp_path/'empty', empty, 'Prompt', LearningConfig(workers=1))
    assert read(path)['cards'] == initial['cards']


@pytest.mark.parametrize('bad', [experience(split='val'), experience(split='test'),
    experience(qualified=False), experience(status='infrastructure_failure')])
def test_learning_admission_no_model_calls(tmp_path,bad):
    model = FixtureModel([])
    with pytest.raises(ValueError):
        learn([bad], bank(), tmp_path, model, 'Prompt')
    assert not model.calls


def test_upstream_trace_formatter_never_truncates_and_native_fork_dedup():
    rows = [dict(id='m1', timestamp='01', message=dict(role='assistant',content=[dict(type='thinking',thinking='Plan'),dict(type='toolCall',name='calc',arguments={'x':2})])),
            dict(id='m2', timestamp='02', message=dict(role='toolResult',content='Tool output'))]
    flat = flatten_native(rows + [rows[0]])
    assert len(flat) == 2
    assert '[tool_call]' in flat[0]['content'] and 'Plan' in flat[0]['content']
    repeated = dict(rows[1],id='m3')
    assert len(flatten_native(rows + [repeated])) == 3
    long = 'value ' * 10000
    assert long in fmt_trajectory([dict(role='tool',content=long)],max_chars=10)


def test_binary_evidence_preserved_not_invented():
    rows = [dict(message=dict(role='tool',content=[dict(type='image',data='SYNTHETIC_BINARY'),dict(type='text',text='Text finding')]))]
    original = json.dumps(rows)
    flat, binary = reflection_native(rows)
    assert json.dumps(rows) == original
    assert len(binary) == 1 and binary[0]['sha256']
    assert 'SYNTHETIC_BINARY' not in flat[0]['content'] and 'Text finding' in flat[0]['content']
    assert 'infer no unsupported visual facts' in flat[0]['content']


def test_routing_topk_universal_phrase_boundary_and_stable_order():
    seed = bank([card('global',['*']),card('earlier',['rate']),card('later',['total']),card('two',['growth','rate'])])
    text, meta = render_bank(seed, 'growth rate and total')
    assert meta['card_ids'] == ['global','two']
    text, meta = render_bank(seed, 'corporate')
    assert meta['card_ids'] == ['global']
    text, meta = render_bank(seed, 'rate total')
    assert meta['card_ids'] == ['global','earlier']
    _, meta = render_bank(seed, all_cards=True)
    assert meta['card_ids'] == ['global','earlier','later','two']


def test_upstream_patch_and_gate_retained():
    text, report = apply_patch_with_report('one',dict(edits=[dict(op='append',content='two'),dict(op='replace',target='absent',content='wrong')]))
    assert 'two' in text and report[0]['status'].startswith('applied')
    assert not report[1]['status'].startswith('applied')
    assert evaluate_gate('new',.5,'old',.5,'old',.5,0,1).action == 'reject'
    assert evaluate_gate('new',.6,'old',.5,'old',.5,0,1).action == 'accept_new_best'


def test_validation_uses_current_profile_ranking_not_per_card_gate():
    rows = [dict(id='v',split='val',hard=1,soft=.9,qualified=True,api_requests=3)]
    choices = [dict(name='a',bank=bank(),results=rows,skill_bytes=100),
               dict(name='b',bank=bank(),results=[dict(rows[0],api_requests=2,soft=.8)],skill_bytes=200)]
    assert select_candidate(choices,['v'],'officeqa')['winner'] == 'b'
    assert select_candidate(choices,['v'],'webshop')['winner'] == 'a'
    with pytest.raises(ValueError, match='Validation'):
        select_candidate([dict(choices[0],results=[dict(rows[0],split='test')])],['v'])
    with pytest.raises(ValueError, match='Validation ids'):
        select_candidate(choices,['v','missing'])


def test_unknown_request_count_never_used_as_zero_for_officeqa():
    rows=[dict(id='v',split='val',hard=1,soft=1,qualified=True,api_requests=None)]
    choices=[dict(name='a',bank=bank(),results=rows)]
    with pytest.raises(ValueError,match='exact API request counts'):
        select_candidate(choices,['v'],'officeqa')
    assert select_candidate(choices,['v'],'webshop')['winner']=='a'

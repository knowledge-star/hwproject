import hashlib
import json
import pytest
from skill_optimizer.research.officeqa import AuditedReflectionParser, ReflectionRecoveryError
from skill_optimizer.storage import read


def extract(text):
    try: return json.loads(text)
    except ValueError: return None


def response(cards):
    return json.dumps(dict(patch=dict(edits=[dict(op='append',content=json.dumps(c)) for c in cards])))


def card():
    return dict(title='Verify units', trigger=['total'], body='Keep units aligned.', required_operations=['sum'])


def test_original_parser_repairs_syntax_retains_response_and_zero_edits(tmp_path):
    parser = AuditedReflectionParser(tmp_path, extract)
    text = response([card()]).replace('}]}}','},]}}')
    parsed = parser(text)
    assert json.loads(parsed['patch']['edits'][0]['content']) == card()
    path = tmp_path/hashlib.sha256(text.encode()).hexdigest()
    assert (path/'response.txt').read_text() == text
    assert read(path/'parse-audit.json')['semantic_content_generated'] is False
    assert parser(response([]))['patch']['edits'] == []


@pytest.mark.parametrize('value',[{}, {'patch':{}}, {'patch':{'edits':'bad'}},
    {'patch':{'edits':[dict(op='delete',content=json.dumps(card()))]}},
    {'patch':{'edits':[dict(op='append',content=json.dumps(dict(title='incomplete')))]}}])
def test_parser_rejects_unrecoverable_schema(tmp_path,value):
    parser = AuditedReflectionParser(tmp_path,extract)
    with pytest.raises(ReflectionRecoveryError):parser(json.dumps(value))
    assert read(next(tmp_path.glob('*/parse-audit.json')))['status']=='rejected'


def test_parser_cannot_invent_content_or_accept_multiple_objects(tmp_path):
    parser = AuditedReflectionParser(tmp_path,lambda text:json.loads(response([dict(card(),body='Invented text')])) )
    with pytest.raises(ReflectionRecoveryError,match='changed/introduced'):parser(response([card()]))
    parser = AuditedReflectionParser(tmp_path/'multi',extract)
    with pytest.raises(ReflectionRecoveryError,match='Ambiguous'):parser(response([])+' '+response([]))


def test_operation_vocab_is_per_instance_no_leaks(tmp_path):
    web = dict(card(),required_operations=['search'])
    parser = AuditedReflectionParser(tmp_path/'web',extract,operations={'search'})
    assert parser(response([web]))
    default = AuditedReflectionParser(tmp_path/'default',extract)
    with pytest.raises(ReflectionRecoveryError,match='supported-operation'):default(response([web]))

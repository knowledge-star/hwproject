"""Current experience-card algorithm, extracted without a new optimization rule.

Original dispatcher, audited parser, RawPatch and patch application are reused.
OfficeQA's sort/sanitize/body-dedup/append operations remain in the same order.
Validation ranking is a separate stage, never feedback to the reflector.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import re
import uuid
from ._vendor.skillopt.gradient import reflect as reflect_source
from ._vendor.skillopt.optimizer.skill import apply_patch_with_report
from ._vendor.skillopt.types import RawPatch
from .models import CachedModel
from .adapters.base import PendingExecution
from .research.officeqa import AuditedReflectionParser, sanitize_card
from .research.binary import reflection_native
from .research import officeqa_routing as routing
from .storage import digest, dump, immutable, read, sha, implementation_digest


@dataclass(frozen=True)
class LearningConfig:
    minibatch_size: int = 5
    edit_budget: int = 3
    workers: int = 8
    random_seed: int = 20261103
    failure_only: bool = False
    operations: tuple[str, ...] = ('lookup', 'sum', 'mean', 'median', 'percent_change',
        'percent_difference', 'share', 'ratio', 'correlation', 'percentile', 'linear_trend', 'expression')

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.minibatch_size, self.edit_budget, self.workers)):
            raise ValueError('minibatch_size, edit_budget and workers must be positive integers')
        if type(self.random_seed) is not int or type(self.failure_only) is not bool:
            raise ValueError('Invalid seed/failure_only')


def _body_key(body):
    # Byte-for-byte same canonicalization as oqs.learn.main.
    return hashlib.sha256(re.sub(r'\s+', ' ', body.lower()).encode()).hexdigest()


def _reflector(model, parser):
    """A private module instance retains the original dispatcher exactly.

    Matches oqs.learn's model/parser injection, avoiding its process-wide mutable
    module state. Concurrent independent learners cannot change each other's I/O.
    """
    spec = importlib.util.spec_from_file_location('skillopt_reflect_' + uuid.uuid4().hex, reflect_source.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def call_model(*args, **kwargs):
        try:
            return model(*args, **kwargs)
        except PendingExecution:
            # Upstream catches ordinary exceptions as failed reflections. Let it
            # finish dispatching batches without manufacturing a patch or traceback.
            return '', {}

    def parse_reply(text):
        if text == '' and model.pending:
            return None
        return parser(text)

    module.chat_optimizer, module.extract_json = call_model, parse_reply
    return module


def learn(experiences, seed_bank, output, model, system_prompt, config=None):
    """Train-only full trajectories -> minibatch reflections -> immutable bank.

    Returns bank.json. No Runtime/Benchmark/absolute-server-path dependencies.
    Raw native conversation is retained separately from its textual adaptation.
    """
    config = config or LearningConfig()
    output = Path(output)
    if not experiences or any(e.task.split != 'train' for e in experiences):
        raise ValueError('Learner admits nonempty Train experiences only')
    ids = [e.task.id for e in experiences]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate training ids')
    routing._validate_bank(seed_bank)
    for e in experiences:
        e.execution.validate(e.task.public())
        if e.execution.status == 'infrastructure_failure' or not e.score.qualified:
            raise ValueError('Unqualified infrastructure outcome cannot enter reflection')
    manifest = dict(implementation_digest=implementation_digest(), algorithm='officeqa_experience_cards', seed_bank_digest=digest(seed_bank),
                    experiences_digest=digest([asdict(e) for e in experiences]),
                    model=model.identity(), prompt_digest=digest(system_prompt),
                    config=json.loads(json.dumps(asdict(config))), train_ids=ids,
                    test_accessed=False, validation_in_optimizer=False)
    immutable(output / 'learning-manifest.json', manifest)
    if (output / 'bank.json').exists():
        if not (output / 'learning-audit.json').exists():
            raise ValueError('Incomplete bank commit')
        if read(output / 'learning-audit.json')['bank_digest'] != digest(read(output / 'bank.json')):
            raise ValueError('Committed bank drift')
        return output / 'bank.json'
    results = []
    for e in experiences:
        folder = output / 'predictions' / e.task.id
        immutable(folder / 'native-conversation.json', e.execution.conversation)
        text, binary = reflection_native(e.execution.conversation)
        # Some harnesses expose tool results separately; retain them for reflection
        # in addition to, never instead of, the full original conversation.
        if e.execution.tool_feedback:
            text.append(dict(role='system', content='Separately exported actual tool feedback:\n' +
                        json.dumps(e.execution.tool_feedback, ensure_ascii=False)))
        dump(folder / 'conversation.json', text)
        dump(folder / 'binary-evidence-index.json', dict(binary_blocks=binary,
             native_sha256=sha(folder / 'native-conversation.json'), text_only_reflection=True))
        results.append(dict(id=e.task.id, hard=e.score.hard, soft=e.score.soft,
                     task_description=e.task.prompt, task_type=e.task.task_type,
                     reference_text=e.task.reference_text or e.task.answer,
                     predicted_answer=e.execution.final_answer,
                     n_turns=e.execution.api_requests, fail_reason=e.score.feedback))
    dump(output / 'rollouts.json', results)
    cached = CachedModel(model, output / 'optimizer')
    parser = AuditedReflectionParser(output / 'parser-audit', reflect_source.extract_json,
                                     operations=set(config.operations))
    reflect = _reflector(cached, parser)
    skill = seed_bank['base_skill'] + '\n\n' + '\n\n'.join(c['title'] + '\n' + c['body'] for c in seed_bank['cards'])
    patches = reflect.run_minibatch_reflect(results, skill, str(output / 'predictions'), str(output / 'patches'),
              workers=config.workers, failure_only=config.failure_only, minibatch_size=config.minibatch_size,
              edit_budget=config.edit_budget, random_seed=config.random_seed, error_system=system_prompt,
              success_system=system_prompt, skill_aware_reflection=False)
    if cached.pending:
        raise PendingExecution('\n'.join(cached.pending))
    expected = sum((sum(bool(r['hard']) == kind for r in results) + config.minibatch_size - 1) // config.minibatch_size
                   for kind in ([False] if config.failure_only else [True, False]))
    if len(patches) != expected or any(p is None for p in patches):
        raise RuntimeError('Unresolved reflections; preserve model caches and inspect before resume')
    patches.sort(key=lambda p: json.dumps(p, sort_keys=True))
    dump(output / 'raw-patches.json', patches)
    cards = copy.deepcopy(seed_bank['cards'])
    seen = {_body_key(c['body']) for c in cards}
    decisions = []
    for index, patch in enumerate(patches):
        typed = RawPatch.from_dict(patch)
        if typed is None:
            continue
        for edit in typed.patch.edits:
            try:
                card, reason = sanitize_card(json.loads(edit.content))
            except (ValueError, TypeError):
                card, reason = None, 'malformed_card_json'
            if card is None:
                decisions.append(dict(patch=index, accepted=False, reason=reason))
                continue
            key = _body_key(card['body'])
            if key in seen:
                decisions.append(dict(patch=index, accepted=False, reason='duplicate'))
                continue
            content, report = apply_patch_with_report('', dict(edits=[dict(op='append', content=card['body'])]))
            if not report or not report[0]['status'].startswith('applied'):
                raise RuntimeError('Upstream append was not applied')
            card.update(id='learned-' + key[:12], body=content.strip(),
                        provenance=[dict(split='train', train_ids=ids, patch=index,
                           source_type=typed.source_type, reflection_artifact='raw-patches.json')])
            cards.append(card)
            seen.add(key)
            decisions.append(dict(patch=index, card_id=card['id'], accepted=True, patch_application=report))
    # Domain/runtime deployment flags belong to the supplied bank, not reflection.
    bank = dict(seed_bank, version=output.name, cards=cards)
    routing._validate_bank(bank)
    dump(output / 'learning-audit.json', dict(decisions=decisions,
         learned_count=len(cards)-len(seed_bank['cards']), train_ids=ids,
         bank_digest=digest(bank), validation_in_optimizer=False, test_accessed=False))
    dump(output / 'bank.json', bank)  # final commit marker, after durable audit
    return output / 'bank.json'


def render_bank(bank, question='', profile='portable', all_cards=False):
    """Same lexical trigger ranking/universal exemption/stable-order routing.

    The portable renderer changes only metadata/header, omits the OfficeQA-only
    contract tool, and preserves card text. Keep the JSON bank for per-task routing.
    """
    cards, config = routing._validate_bank(bank)
    if profile != 'portable':
        raise ValueError('Use research.officeqa_routing.render_skill for exact OfficeQA rendering')
    if config.get('contract', False):
        raise ValueError('OfficeQA contract requires its runtime; portable rendering needs contract=false')
    question_tokens = routing._tokens(question)
    scores = {c['id']: routing._trigger_score(question_tokens, c['trigger']) for c in cards}
    if all_cards or config.get('routing', 'topk') == 'all':
        selected = cards
    else:
        universal = [c for c in cards if '*' in c['trigger']]
        candidates = [c for c in cards if '*' not in c['trigger'] and scores[c['id']] > 0]
        candidates.sort(key=lambda c: -scores[c['id']])
        picked = {c['id'] for c in universal + candidates[:config.get('topk', 6)]}
        selected = [c for c in cards if c['id'] in picked]
    text = '---\nname: portable-skill\ndescription: Conditional procedures learned from training execution evidence.\n---\n\n'
    text += bank['base_skill'] + '\n\n## Routed experience\n'
    for card in selected:
        text += f"\n### {card['title']}\n\n{card['body'].strip()}\n"
    return text, dict(card_ids=[c['id'] for c in selected], scores=scores,
                      bank_digest=digest(bank), version=bank['version'], all_cards=all_cards)


def select_candidate(candidates, expected_ids, policy='officeqa'):
    """Pure final selection. Exact OfficeQA / WebShop ranking policies.

    Each candidate: name, bank, results [{id, hard, soft, qualified, api_requests}].
    No training/reflection here. Candidates must cover exactly the same fixed Val.
    """
    if not candidates or not expected_ids or len(set(expected_ids)) != len(expected_ids):
        raise ValueError('Need candidates and a nonempty fixed Validation set')
    ranked = []
    for candidate in candidates:
        rows = candidate['results']
        if len(rows) != len(expected_ids) or {r['id'] for r in rows} != set(expected_ids):
            raise ValueError('Incomplete/duplicate/different Validation ids')
        if any(not r['qualified'] or r.get('split') != 'val' for r in rows):
            raise ValueError('Only complete qualified Validation outcomes may select Skills')
        bank = candidate['bank']
        stats = dict(name=candidate['name'], successes=sum(r['hard'] for r in rows),
                     mean_requests=(sum(r['api_requests'] for r in rows)/len(rows) if all(type(r['api_requests']) is int for r in rows) else None),
                     mean_reward=sum(r['soft'] for r in rows)/len(rows),
                     # file bytes used by OQ are provided by the orchestrator.
                     skill_bytes=candidate.get('skill_bytes', len(json.dumps(bank, ensure_ascii=False).encode())),
                     body_chars=len(bank['base_skill'])+sum(len(c['body']) for c in bank['cards']))
        if policy == 'officeqa':
            if stats['mean_requests'] is None:
                raise ValueError('OfficeQA selection requires exact API request counts; declare a supported policy before evaluation')
            key = (-stats['successes'], stats['mean_requests'], stats['skill_bytes'], stats['name'])
        elif policy == 'webshop':
            key = (-stats['successes'], -stats['mean_reward'], stats['body_chars'], stats['name'])
        else:
            raise ValueError('selection policy must be officeqa or webshop')
        ranked.append((key, stats))
    ranked.sort(key=lambda pair: pair[0])
    return dict(winner=ranked[0][1]['name'], policy=policy, ranking=[stats for _, stats in ranked],
                validation_ids=list(expected_ids), test_accessed=False)

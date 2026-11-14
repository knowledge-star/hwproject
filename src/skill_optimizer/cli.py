import argparse
import importlib
import json
from pathlib import Path
import sys
from .contracts import Task
from .core import LearningConfig, render_bank
from .pipeline import SkillOptimizer
from .adapters.base import PendingExecution
from .storage import read


def _object(name):
    module, attr = name.split(':', 1)
    return getattr(importlib.import_module(module), attr)


def _build(kind, options, choices):
    cls = choices.get(kind)
    return _object(cls or kind)(**options)


def load_config(path):
    path = Path(path).resolve()
    cfg = read(path)
    base = path.parent
    def resolve(value):
        p = Path(value)
        return p if p.is_absolute() else (base / p).resolve()
    tasks = [Task(**row) for row in read(resolve(cfg['tasks']))]
    seed = read(resolve(cfg['seed_bank']))
    prompt = resolve(cfg['reflection_prompt']).read_text(encoding='utf-8')
    adapter_spec = dict(cfg['adapter'])
    kind = adapter_spec.pop('kind')
    if 'command' in adapter_spec:
        adapter_spec['command'] = [part.replace('{project}', str(base.parent)) for part in adapter_spec['command']]
    if 'native_config_file' in adapter_spec:
        adapter_spec['native_config'] = read(resolve(adapter_spec.pop('native_config_file')))
    adapter = _build(kind, adapter_spec, {
        'synthetic': 'skill_optimizer.adapters.synthetic:SyntheticHarness',
        'file': 'skill_optimizer.adapters.exchange:FileExchangeAdapter',
        'command': 'skill_optimizer.adapters.exchange:CommandAdapter',
        'openclaw': 'skill_optimizer.adapters.openclaw:OpenClawAdapter',
        'xiaoyi': 'skill_optimizer.adapters.xiaoyi:XiaoyiWorkAdapter'})
    judge_spec = dict(cfg.get('judge', {'kind': 'exact_match'}))
    judge = _build(judge_spec.pop('kind'), judge_spec, {
        'exact_match': 'skill_optimizer.judges:ExactMatchJudge',
        'external': 'skill_optimizer.judges:ExternalFeedbackJudge'})
    model_spec = dict(cfg['model'])
    model = _build(model_spec.pop('kind'), model_spec, {
        'synthetic': 'skill_optimizer.models:SyntheticReflectionModel',
        'file_reflection': 'skill_optimizer.reflection_exchange:FileExchangeReflectionModel',
        'openai_compatible': 'skill_optimizer.models:OpenAICompatibleModel'})
    learning = dict(cfg.get('learning', {}))
    if 'operations' in learning:
        learning['operations'] = tuple(learning['operations'])
    optimizer = SkillOptimizer(adapter, judge, model, prompt, LearningConfig(**learning))
    return cfg, tasks, seed, optimizer


def main(argv=None):
    parser = argparse.ArgumentParser(description='Portable experience-card optimizer')
    subs = parser.add_subparsers(dest='command', required=True)
    run = subs.add_parser('run')
    run.add_argument('--config', required=True, type=Path)
    run.add_argument('--output', required=True, type=Path)
    export = subs.add_parser('export')
    export.add_argument('--bank', required=True, type=Path)
    export.add_argument('--output', required=True, type=Path)
    mode = export.add_mutually_exclusive_group(required=True)
    mode.add_argument('--question')
    mode.add_argument('--all-cards', action='store_true')
    probe = subs.add_parser('probe-openclaw')
    probe.add_argument('--output', required=True, type=Path)
    probe.add_argument('--command', dest='cli_command', nargs='+', default=['openclaw'])
    pending = subs.add_parser('pending', help='List file requests for the conversation controller')
    pending.add_argument('--output', required=True, type=Path)
    submit = subs.add_parser('submit-reflection', help='Bind an actual reflection reply to its request')
    submit.add_argument('--request', required=True, type=Path)
    submit.add_argument('--reply', required=True, type=Path)
    submit.add_argument('--metadata', type=Path, help='Actual session/evidence metadata JSON object')
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            cfg, tasks, seed, optimizer = load_config(args.config)
            result = optimizer.run([t for t in tasks if t.split == 'train'], [t for t in tasks if t.split == 'val'],
                        seed, args.output, cfg.get('rounds', 1), cfg.get('selection_policy', 'officeqa'))
            print('Final Skill:', result)
        elif args.command == 'export':
            text, metadata = render_bank(read(args.bank), args.question or '', all_cards=args.all_cards)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding='utf-8')
            print(json.dumps(dict(path=str(args.output), **metadata), ensure_ascii=False))
        elif args.command == 'pending':
            from .reflection_exchange import exchange_status
            print(json.dumps(exchange_status(args.output), ensure_ascii=False, indent=2))
        elif args.command == 'submit-reflection':
            from .reflection_exchange import write_reflection_response
            metadata = read(args.metadata) if args.metadata else {}
            if not isinstance(metadata, dict):
                raise ValueError('Reflection metadata must be an object')
            print(write_reflection_response(args.request, args.reply.read_text(encoding='utf-8'), metadata))
        else:
            from .adapters.openclaw import OpenClawAdapter
            bank = dict(version='probe', base_skill='Inspect current evidence before producing an answer.',
                        cards=[], config=dict(contract=False))
            text, _ = render_bank(bank)
            print(json.dumps(OpenClawAdapter(command=args.cli_command).probe(text, args.output), ensure_ascii=False))
    except PendingExecution as exc:
        print(str(exc))
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())

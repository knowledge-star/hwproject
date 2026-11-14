"""Small orchestration layer around the actual card algorithm and Harness seam."""
from dataclasses import asdict
from pathlib import Path
from .contracts import Execution, Experience, Score
from .core import LearningConfig, learn, render_bank, select_candidate
from .storage import digest, dump, exclusive, immutable, read, sha, implementation_digest


class SkillOptimizer:
    def __init__(self, adapter, judge, model, system_prompt, learning=None):
        self.adapter, self.judge, self.model = adapter, judge, model
        self.system_prompt, self.learning = system_prompt, learning or LearningConfig()

    def _execute(self, task, bank, folder):
        text, routing = render_bank(bank, task.prompt)
        spec = dict(task=asdict(task), bank_digest=digest(bank), skill_digest=digest(text),
                    adapter=self.adapter.identity(), judge=self.judge.identity())
        immutable(folder / 'inputs.json', spec)  # host only; never sent to Adapter
        dump(folder / 'routing.json', routing)
        result_path = folder / 'execution.json'
        if result_path.exists():
            proof = read(folder / 'execution-proof.json')
            if proof['sha256'] != sha(result_path):
                raise ValueError('Execution cache drift')
            execution = Execution(**read(result_path)).validate(task.public())
        else:
            execution = self.adapter.execute(task.public(), text, folder / 'exchange').validate(task.public())
            # Commit a failed infrastructure delivery too; never resample it.
            dump(result_path, asdict(execution))
            dump(folder / 'execution-proof.json', dict(sha256=sha(result_path)))
        score_path = folder / 'score.json'
        if score_path.exists():
            if read(folder / 'score-proof.json')['sha256'] != sha(score_path):
                raise ValueError('Score cache drift')
            score = Score(**read(score_path))
        else:
            score = self.judge.score(task, execution)
            dump(score_path, asdict(score))
            dump(folder / 'score-proof.json', dict(sha256=sha(score_path)))
        if execution.status == 'infrastructure_failure' or not score.qualified:
            raise RuntimeError(f'Unqualified outcome: {task.id}; inspect delivery/judge, no automatic rerun')
        return Experience(task, execution, score)

    def run(self, train_tasks, val_tasks, seed_bank, output, rounds=1, selection_policy='officeqa'):
        output = Path(output).resolve()
        if type(rounds) is not int or rounds < 1:
            raise ValueError('rounds must be a positive integer')
        if not train_tasks or not val_tasks or any(t.split != 'train' for t in train_tasks) or any(t.split != 'val' for t in val_tasks):
            raise ValueError('Separate nonempty Train and Validation tasks required')
        ids = [t.id for t in train_tasks + val_tasks]
        if len(ids) != len(set(ids)):
            raise ValueError('Train/Validation ids overlap or repeat')
        manifest = dict(implementation_digest=implementation_digest(), train_tasks=[asdict(t) for t in train_tasks], val_tasks=[asdict(t) for t in val_tasks],
                        seed=seed_bank, rounds=rounds, selection_policy=selection_policy,
                        adapter=self.adapter.identity(), judge=self.judge.identity(), model=self.model.identity(),
                        learning=asdict(self.learning), prompt_digest=digest(self.system_prompt))
        # JSON normalizes tuple operation vocabulary for exact resume equality.
        import json
        manifest = json.loads(json.dumps(manifest))
        with exclusive(output / 'run.lock'):
            immutable(output / 'run-manifest.json', manifest)
            candidate_banks = [('seed', seed_bank)]
            dump(output / 'seed/bank.json', seed_bank)
            current = seed_bank
            # Optional repeated append chain: Train re-executes with each bank.
            # There is no invented per-card gate or validation-based rewriting.
            for number in range(1, rounds + 1):
                name = f'round-{number:03d}'
                experiences = [self._execute(t, current, output / name / 'train' / t.id) for t in train_tasks]
                path = learn(experiences, current, output / name / 'learning', self.model, self.system_prompt, self.learning)
                current = read(path)
                candidate_banks.append((name, current))
            choices = []
            for name, bank in candidate_banks:
                path = output / name / 'bank.json'
                dump(path, bank)
                rows = []
                for task in val_tasks:
                    e = self._execute(task, bank, output / name / 'val' / task.id)
                    rows.append(dict(id=task.id, split='val', hard=e.score.hard, soft=e.score.soft,
                                     qualified=e.score.qualified, api_requests=e.execution.api_requests))
                dump(output / name / 'validation.json', rows)
                choices.append(dict(name=name, bank=bank, results=rows, skill_bytes=path.stat().st_size))
            selection = select_candidate(choices, [t.id for t in val_tasks], selection_policy)
            dump(output / 'selection.json', selection)
            winner = next(c['bank'] for c in choices if c['name'] == selection['winner'])
            immutable(output / 'final/bank.json', winner)
            # SKILL.md is a full-bank static export; per-task routing still uses bank.json.
            skill, _ = render_bank(winner, all_cards=True)
            exported = self.adapter.export_skill(skill, output / 'final/SKILL.md')
            dump(output / 'final/freeze.json', dict(winner=selection['winner'], bank_sha256=sha(output / 'final/bank.json'),
                static_skill_sha256=sha(exported), selection_sha256=sha(output / 'selection.json'),
                export='all cards; use bank.json + render for per-task top-k deployment',
                adapter=self.adapter.identity(), model=self.model.identity(), test_used_for_selection=False))
            return output / 'final/SKILL.md'

"""Host-private task/judge data is never passed to HarnessAdapter.execute."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
import math
import re
from ._vendor.skillopt.types import RolloutResult, RawPatch, Edit, Patch  # reused upstream types


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    split: str
    answer: str = ''
    task_type: str = 'generic'
    reference_text: str = ''  # Train analyst only; never target runtime.
    public_metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', self.id) or self.id in {'.', '..'}:
            raise ValueError('Task id must be a safe single path component')
        if self.split not in {'train', 'val', 'test'} or not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError('Task needs a public prompt and train/val/test split')

    def public(self):
        return dict(id=self.id, prompt=self.prompt, split=self.split,
                    task_type=self.task_type, metadata=self.public_metadata)


@dataclass
class Execution:
    task_id: str
    final_answer: str
    conversation: list[dict]
    status: str = 'complete'  # complete | normal_failure | infrastructure_failure
    api_requests: int | None = None
    tool_feedback: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, task):
        if self.task_id != task['id']:
            raise ValueError('Execution belongs to another task')
        if self.status not in {'complete', 'normal_failure', 'infrastructure_failure'}:
            raise ValueError('Unknown execution status')
        if not isinstance(self.final_answer, str) or not isinstance(self.conversation, list) or not self.conversation:
            raise ValueError('Full nonempty conversation and final_answer text are required')
        if any(not isinstance(row, dict) for row in self.conversation):
            raise ValueError('Conversation rows must be objects')
        if self.api_requests is not None and (type(self.api_requests) is not int or self.api_requests < 0):
            raise ValueError('api_requests must be a nonnegative integer or null when unknown')
        if not isinstance(self.tool_feedback, list) or not isinstance(self.metadata, dict):
            raise ValueError('Invalid feedback/metadata')
        return self


@dataclass(frozen=True)
class Score:
    hard: float
    soft: float
    feedback: str
    qualified: bool = True

    def __post_init__(self):
        if type(self.qualified) is not bool or not isinstance(self.feedback, str):
            raise ValueError('qualified must be boolean and feedback must be text')
        if self.hard not in (0, 1) or not math.isfinite(self.soft) or not 0 <= self.soft <= 1:
            raise ValueError('Experience-card hard must be binary; soft must be finite in [0,1]')


@dataclass
class Experience:
    task: Task
    execution: Execution
    score: Score


class HarnessAdapter(Protocol):
    """One Main Agent execution. Export/load/update Skills use Markdown snapshots.

    execute receives public task only; it must record actual native tool calls,
    results and final delivery, or explicitly stop if unavailable.
    """
    def identity(self) -> dict: ...
    def execute(self, task: dict, skill: str, directory: Path) -> Execution: ...
    def export_skill(self, skill: str, destination: Path) -> Path: ...


class Judge(Protocol):
    def identity(self) -> dict: ...
    def score(self, task: Task, execution: Execution) -> Score: ...


class ReflectionModel(Protocol):
    def identity(self) -> dict: ...
    def __call__(self, system: str, user: str, **kwargs) -> tuple[str, dict]: ...

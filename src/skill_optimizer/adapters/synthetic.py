"""Synthetic runtime for interface tests. This is not an Agent deployment."""
from .base import SkillExportMixin
from ..contracts import Execution


class SyntheticHarness(SkillExportMixin):
    def identity(self):
        return dict(kind='synthetic_harness', real_agent=False, version=1)

    def execute(self, task, skill, directory):
        numbers = task['metadata']['numbers']
        enabled = 'add all provided operands' in skill
        value = sum(numbers) if enabled else numbers[0]
        feedback = dict(type='tool_call', cmd='sum(public operands)', obs=str(sum(numbers)))
        conversation = [dict(role='user', content=task['prompt'])]
        if enabled:
            conversation.append(feedback)
        conversation.append(dict(role='assistant', content=str(value)))
        return Execution(task['id'], str(value), conversation, api_requests=1,
                         tool_feedback=[feedback] if enabled else [],
                         metadata=dict(synthetic=True, real_agent=False)).validate(task)

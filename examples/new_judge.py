"""Config example: kind='examples.new_judge:MyJudge' from the project directory.
Put production plugins in an installed Python package for reliable imports.
"""
from skill_optimizer.contracts import Score


class MyJudge:
    def identity(self):
        # Include authoritative scorer version/config so resume detects drift.
        return dict(kind='my_judge_example', version=1)

    def score(self, task, execution):
        # Replace with your existing host-side scorer; never send task.answer
        # or its private reference to the solving Agent.
        passed = execution.final_answer.strip() == task.answer.strip()
        return Score(float(passed), float(passed), 'Example checker pass=' + str(passed),
                     execution.status != 'infrastructure_failure')

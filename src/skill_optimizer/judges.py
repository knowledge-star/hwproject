"""Judge runs on the host, after Agent execution; no gold answer in requests."""
from .contracts import Score


class ExactMatchJudge:
    """Example only. Replace with the task's existing authoritative scorer."""
    def identity(self):
        return dict(kind='exact_match', version=1, normalization='strip only')

    def score(self, task, execution):
        passed = execution.final_answer.strip() == task.answer.strip()
        return Score(float(passed), float(passed), 'Exact-match pass=' + str(passed),
                     execution.status != 'infrastructure_failure')


class ExternalFeedbackJudge:
    """Scores independently supplied by an authorized external judge/operator.

    The exchange request hash binds delivery, task and Skill; this is not a
    cryptographic attestation of score correctness. Trust the authorized scorer,
    not self-evaluation emitted by the solving Agent.
    """
    def identity(self):
        return dict(kind='external_feedback', version=1)

    def score(self, task, execution):
        row = execution.metadata.get('judge_feedback')
        if not isinstance(row, dict) or not {'hard', 'soft', 'feedback', 'qualified'} <= row.keys():
            raise ValueError('Missing externally supplied judge_feedback')
        score = Score(**{k: row[k] for k in ['hard', 'soft', 'feedback', 'qualified']})
        if execution.status == 'infrastructure_failure' and score.qualified:
            raise ValueError('Infrastructure failure cannot be score-qualified')
        return score

from pathlib import Path


class SkillExportMixin:
    def export_skill(self, skill, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(skill, encoding='utf-8')
        return path


class PendingExecution(RuntimeError):
    """No response yet; CLI exits 3, same command resumes exact request."""

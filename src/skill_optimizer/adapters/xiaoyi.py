"""小艺 Work 文件交换骨架；未验证任何内部 API 或原生 Skill 管理能力。"""
from .exchange import FileExchangeAdapter


class XiaoyiWorkAdapter(FileExchangeAdapter):
    def identity(self):
        return dict(kind='xiaoyi_work_manual_exchange', schema=1,
                    api_verified=False, native_skill_update_verified=False,
                    trace_export_verified=False)

    # Replace execute only after verifying the actual environment's supported
    # capabilities. FileExchangeAdapter already supplies a resumable manual
    # request/response flow. Never fabricate missing tool traces or infer reward.

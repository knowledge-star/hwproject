"""Replacement I/O seam. No original providers, credentials or config loading."""
def chat_optimizer(*args, **kwargs):
    raise RuntimeError("Inject a ReflectionModel into the learner; no default model provider")

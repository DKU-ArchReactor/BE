"""Numeric-only per-request observations: never log prompts, identities or errors."""
import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)


def configure_usage_logging():
    # Dedicated JSON records; leave SDK/root logger levels untouched.
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.propagate = False

TOKEN_KEYS = ('inputTokens', 'outputTokens', 'totalTokens')


def token_usage(value) -> dict:
    usage = {}
    for source, target in zip(('prompt_tokens', 'completion_tokens', 'total_tokens'), TOKEN_KEYS):
        count = getattr(value, source, None)
        if type(count) is int and count >= 0:
            usage[target] = count
    return usage


class Observation:
    def __init__(self):
        self.request_id = uuid4().hex
        self.usage = {}

    def record(self, stage, usage):
        self.usage[stage] = {key: value for key, value in usage.items()
                             if key in TOKEN_KEYS and type(value) is int and value >= 0}

    def finish(self, outcome):
        # Only include totals known for every invoked stage. {} means unknown.
        total = {key: sum(stage[key] for stage in self.usage.values())
                 for key in TOKEN_KEYS if self.usage and all(key in stage for stage in self.usage.values())}
        logger.info(json.dumps({'event': 'assistant_usage', 'requestId': self.request_id,
                               'outcome': outcome, 'stages': self.usage, 'total': total}))

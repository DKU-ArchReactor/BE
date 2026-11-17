"""Opt-in live SOLID evaluation. Run as python -m scripts.evaluate_assistant_domain.

Uses normal runtime configuration; never prints prompts, replies, credentials or user IDs.
Makes billed/shared-quota classification calls only; no DB, app configuration or deployment changes.
"""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path

from app.core.config import settings
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError
from app.services.assistant.classifier import TopicClassifier
from app.services.assistant.telemetry import Observation


async def evaluate(cases, repeats=1):
    classifier = TopicClassifier()
    records = []
    for repeat in range(repeats):
        for case in cases:
            observation = Observation()
            record = {'id': case['id'], 'repeat': repeat + 1, 'expected': case['expected']}
            try:
                record['actual'] = (await classifier.classify(
                    ChatRequest(messages=case['messages']), observation)).value
            except AgentError as error:
                record['actual'] = 'ERROR'
                record['error_code'] = error.code
            record['usage'] = observation.usage.get('classification', {})
            records.append(record)
    totals = Counter(f"{r['expected']}->{r['actual']}" for r in records)
    return {'model': settings.SOLID_LLM_MODEL, 'format': settings.SOLID_LLM_CLASSIFICATION_FORMAT,
            'count': len(records), 'exact_matches': sum(r['expected'] == r['actual'] for r in records),
            'false_blocks': sum(r['expected'] == 'ALLOW' and r['actual'] not in ('ALLOW', 'ERROR') for r in records),
            'false_allows': sum(r['expected'] != 'ALLOW' and r['actual'] == 'ALLOW' for r in records),
            'errors': sum(r['actual'] == 'ERROR' for r in records),
            'confusion': dict(totals), 'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[1] /
                        'tests/fixtures/assistant_domain_cases.json').read_text())
    print(json.dumps(asyncio.run(evaluate(cases, args.repeats)), ensure_ascii=False))


if __name__ == '__main__':
    main()

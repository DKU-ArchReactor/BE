"""Opt-in SOLID evaluation with synthetic CORE evidence; no DB or deployment changes.

Run: python -m scripts.evaluate_assistant_context
Only labels, numeric usage and pass/fail are printed. No prompts or answer bodies.
This checks factual extraction and abstention, not every natural-language explanation.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.schemas.assistant import ChatRequest
from app.services.assistant.classifier import TopicClassifier
from app.services.assistant.guarded import GuardedProvider
from app.services.assistant.telemetry import Observation
from app.core.config import settings


def matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(matches(a, b) for a, b in zip(actual, expected))
    if type(expected) in (float, int):
        return type(actual) in (float, int) and abs(actual - expected) < 0.00001
    if isinstance(expected, str) and expected.startswith('0x'):
        try:
            return isinstance(actual, str) and actual.lower().startswith('0x') and int(actual, 16) == int(expected, 16)
        except ValueError:
            return False
    return type(actual) is type(expected) and actual == expected


async def evaluate(cases):
    records = []
    for case in cases:
        request = ChatRequest(messages=[{'role': 'user', 'content': case['question']}],
                              editor_source=case.get('editor_source'))
        request._execution_context = case['context']  # Trusted synthetic fixture, never an HTTP input.
        observation = Observation()
        record = {'id': case['id'], 'expected_decision': case['decision']}
        class Classifier:
            async def classify(self, request, ignored):
                decision = await TopicClassifier().classify(request, observation)
                record['decision'] = decision.value
                return decision
        try:
            async with asyncio.timeout(settings.ASSISTANT_TIMEOUT_SECONDS):
                if case['expected'] is None:
                    record['decision'] = (await Classifier().classify(request, observation)).value
                else:
                    events = [event async for event in GuardedProvider(classifier=Classifier()).stream(request)]
                    if record.get('decision') != 'ALLOW':
                        record['passed'] = False
                        record['failure_kind'] = 'classification'
                        record['classification_usage'] = observation.usage.get('classification', {})
                        records.append(record)
                        continue
                    record['stop_reason'] = events[-1].get('stop_reason') if events else None
                    record['complete'] = bool(events and events[-1].get('type') == 'done' and record['stop_reason'] == 'end_turn')
                    record['answer_usage'] = events[-1].get('usage', {}) if events else {}
                    record['reference_match'] = bool(events) and events[-1].get('context') == (
                        case['context']['reference'] if case['context'] else None)
                    body = ''.join(e['text'] for e in events if e['type'] == 'delta')
                    # Fact extraction permits fences/prose, independent of content accuracy.
                    start, end = body.find('{'), body.rfind('}')
                    try:
                        parsed = json.loads(body[start:end+1])
                    except (ValueError, TypeError):
                        record['format_valid'] = False
                        record['failure_kind'] = 'format' if record['complete'] else 'incomplete'
                        parsed = None
                    else:
                        record['format_valid'] = isinstance(parsed, dict)
                    record['facts_match'] = matches(parsed, case['expected'])
                    record['mismatch_fields'] = [k for k, v in case['expected'].items()
                        if not isinstance(parsed, dict) or k not in parsed or not matches(parsed[k], v)]
                    if not record['complete']:
                        record['failure_kind'] = 'incomplete'
                    elif not record.get('format_valid'):
                        record['failure_kind'] = 'format'
                    elif not record['facts_match']:
                        record['failure_kind'] = 'facts'
            record['passed'] = (record['decision'] == case['decision'] and record.get('facts_match', True)
                                and record.get('reference_match', True) and record.get('complete', True))
        except Exception as error:
            record['passed'] = False
            record['error_type'] = type(error).__name__
            record['failure_kind'] = 'transport'
        record['classification_usage'] = observation.usage.get('classification', {})
        records.append(record)
    return {'model': settings.SOLID_LLM_MODEL, 'count': len(records),
            'passed': sum(r['passed'] for r in records), 'records': records}


def main():
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, default=Path(__file__).resolve().parents[1] / 'tests/fixtures/assistant_context_cases.json')
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    print(json.dumps(asyncio.run(evaluate(cases)), ensure_ascii=False))


if __name__ == '__main__':
    main()

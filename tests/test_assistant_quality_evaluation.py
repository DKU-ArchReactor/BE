"""Evaluator regression: incomplete output must not look like factual success."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from scripts import evaluate_assistant_context as evaluation
from app.services.assistant.policy import Decision

@pytest.mark.parametrize('stop_reason,passed', [('end_turn', True), ('max_tokens', False)])
def test_evaluator_rejects_truncation_even_with_matching_json(monkeypatch, stop_reason, passed):
    class Classifier:
        async def classify(self, request, observation):
            return Decision.ALLOW
    class Provider:
        def __init__(self, classifier):
            self.classifier = classifier
        async def stream(self, request):
            await self.classifier.classify(request, None)
            yield {'type': 'delta', 'text': '{"cpi":2}'}
            yield {'type': 'done', 'stop_reason': stop_reason}
    monkeypatch.setattr(evaluation, 'TopicClassifier', Classifier)
    monkeypatch.setattr(evaluation, 'GuardedProvider', Provider)
    report = asyncio.run(evaluation.evaluate([{'id':'synthetic','question':'CPI?', 'context':None, 'decision':'ALLOW','expected':{'cpi':2}}]))
    assert report['records'][0]['passed'] is passed
    assert 'CPI?' not in json.dumps(report)
    assert '"cpi": 2' not in json.dumps(report)

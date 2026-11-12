"""Domain gate inside the route's single quota reservation and total deadline."""
from contextlib import aclosing

from app.services.assistant.classifier import TopicClassifier
from app.services.assistant.policy import Decision, FIXED_RESPONSES
from app.services.assistant.solid_llm import SolidLLMProvider
from app.services.assistant.telemetry import Observation


class GuardedProvider:
    def __init__(self, classifier=None, answer_factory=None):
        self.classifier = classifier or TopicClassifier()
        self.answer_factory = answer_factory or SolidLLMProvider

    async def stream(self, request):
        observation = Observation()
        outcome = 'interrupted'
        try:
            decision = await self.classifier.classify(request, observation)
            if decision != Decision.ALLOW:
                text = FIXED_RESPONSES[decision]
                outcome = decision.value
                yield {'type': 'delta', 'text': text}
                yield {'type': 'done', 'stop_reason': 'end_turn', 'usage': {}}
                return
            # Construct the answer provider only after ALLOW; no answer call on refusals.
            answer = self.answer_factory(usage_observer=lambda usage: observation.record('answer', usage))
            async with aclosing(answer.stream(request)) as stream:
                async for event in stream:
                    if event['type'] == 'done':
                        outcome = 'ALLOW'
                        if request._execution_context is not None:
                            event = {**event, 'context': request._execution_context['reference']}
                    yield event
        except Exception:
            outcome = 'error'
            raise
        finally:
            observation.finish(outcome)

"""Fail-closed SOLID classification with a bounded, untrusted conversation window."""
import asyncio
import json
import re

from app.core.config import settings
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError
from app.services.assistant.policy import CLASSIFIER_PROMPT, Decision, Topic
from app.services.assistant import solid_llm
from app.services.assistant.telemetry import token_usage


def classification_input(request: ChatRequest) -> str:
    # Only short referential turns need prior user requests. Never use a prior
    # generated answer to determine scope; explicit new topics stand on their own.
    latest = request.messages[-1].content
    followup = len(latest) <= 120 and bool(re.search(
        r'그럼|그러면|그거|그건|이건|왜|다시|더\s*(?:자세|설명|짧)|짧게|요약|예시|차이|그래서|그렇|\b(?:why|then|that|it|more|shorter)\b', latest, re.I))
    history = []
    remaining = 4000
    if followup:
        for message in reversed([m for m in request.messages[:-1] if m.role == 'user'][-4:]):
            content = message.content[-min(1000, remaining):]
            if not content or remaining <= 0:
                break
            history.append({'role': 'user', 'content': content,
                            'truncated': len(content) < len(message.content)})
            remaining -= len(content)
    data = {'recent_history': list(reversed(history)), 'latest_question': latest}
    if request._execution_context is not None:
        ref = request._execution_context['reference']
        data['execution_reference'] = {'mode': ref['mode'], 'cycle': ref['cycle']}
    if request.editor_source is not None:
        source = request.editor_source
        data['editor_source'] = {'language': source.language, 'characters': len(source.content)}
    return json.dumps(data, ensure_ascii=False)


def parse_classification(content: str) -> tuple[Decision, tuple[str, ...]]:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    if not isinstance(content, str) or len(content) > 1024:
        raise ValueError('invalid content')
    value = json.loads(content, object_pairs_hook=unique_keys)
    if not isinstance(value, dict) or set(value) != {'decision', 'topics'} or not isinstance(value['decision'], str):
        raise ValueError('invalid decision object')
    decision = Decision(value['decision'])
    topics = value['topics']
    if (not isinstance(topics, list) or len(topics) > len(Topic)
            or any(not isinstance(t, str) or t not in Topic._value2member_map_ for t in topics)
            or len(set(topics)) != len(topics)
            or bool(topics) != (decision == Decision.ALLOW)):
        raise ValueError('invalid topics')
    return decision, tuple(topics)


class TopicClassifier:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory or solid_llm.gateway_client

    async def classify(self, request, observation) -> Decision:
        request._answer_topics = ()
        observation.record('classification', {})
        if not solid_llm._slots.acquire(blocking=False):
            raise AgentError('MODEL_BUSY', 'AI 요청이 많습니다. 잠시 후 다시 시도해 주세요.')
        try:
            async with asyncio.timeout(settings.ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS):
                async with self.client_factory() as client:
                    options = {}
                    if settings.SOLID_LLM_CLASSIFICATION_FORMAT == 'json_schema':
                        options['response_format'] = {'type': 'json_schema', 'json_schema': {
                            'name': 'topic_decision', 'strict': True, 'schema': {
                                'type': 'object', 'properties': {'decision': {
                                    'type': 'string', 'enum': [item.value for item in Decision]},
                                    'topics': {'type': 'array', 'items': {'type': 'string',
                                        'enum': [item.value for item in Topic]}, 'maxItems': len(Topic)}},
                                'required': ['decision', 'topics'], 'additionalProperties': False}}}
                    result = await client.chat.completions.create(
                        model=settings.SOLID_LLM_MODEL,
                        messages=[{'role': 'system', 'content': CLASSIFIER_PROMPT},
                                  {'role': 'user', 'content': classification_input(request)}],
                        stream=False, max_tokens=256, temperature=0, **options)
                    observation.record('classification', token_usage(result.usage))
                    if len(result.choices) != 1:
                        raise ValueError('invalid choices')
                    choice = result.choices[0]
                    message = choice.message
                    if (choice.index != 0 or choice.finish_reason != 'stop' or message.role != 'assistant'
                            or message.refusal or message.tool_calls or message.function_call):
                        raise ValueError('incomplete or unsupported classification')
                    decision, topics = parse_classification(message.content)
                    request._answer_topics = topics
                    return decision
        except Exception:
            # Cancellation (BaseException) propagates. No retries or unguarded fallback.
            raise AgentError('CLASSIFICATION_UNAVAILABLE',
                             '질문 주제를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.') from None
        finally:
            solid_llm._slots.release()

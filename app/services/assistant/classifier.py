"""Fail-closed SOLID classification with a bounded, untrusted conversation window."""
import asyncio
import json

from app.core.config import settings
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError
from app.services.assistant.policy import CLASSIFIER_PROMPT, Decision
from app.services.assistant import solid_llm
from app.services.assistant.telemetry import token_usage


def classification_input(request: ChatRequest) -> str:
    history = []
    remaining = 4000
    for message in reversed(request.messages[:-1][-6:]):
        if remaining <= 0:
            break
        content = message.content[-min(1000, remaining):]
        history.append({'role': message.role, 'content': content,
                        'truncated': len(content) < len(message.content)})
        remaining -= len(content)
    data = {'recent_history': list(reversed(history)), 'latest_question': request.messages[-1].content}
    if request._execution_context is not None:
        ref = request._execution_context['reference']
        data['execution_reference'] = {'mode': ref['mode'], 'cycle': ref['cycle']}
    if request.editor_source is not None:
        source = request.editor_source
        data['editor_source'] = {'language': source.language, 'content': source.content[:4000],
                                 'truncated': len(source.content) > 4000}
    return json.dumps(data, ensure_ascii=False)


def parse_decision(content: str) -> Decision:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    if not isinstance(content, str) or len(content) > 256:
        raise ValueError('invalid content')
    value = json.loads(content, object_pairs_hook=unique_keys)
    if not isinstance(value, dict) or set(value) != {'decision'} or not isinstance(value['decision'], str):
        raise ValueError('invalid decision object')
    return Decision(value['decision'])


class TopicClassifier:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory or solid_llm.gateway_client

    async def classify(self, request, observation) -> Decision:
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
                                    'type': 'string', 'enum': [item.value for item in Decision]}},
                                'required': ['decision'], 'additionalProperties': False}}}
                    result = await client.chat.completions.create(
                        model=settings.SOLID_LLM_MODEL,
                        messages=[{'role': 'system', 'content': CLASSIFIER_PROMPT},
                                  {'role': 'user', 'content': classification_input(request)}],
                        stream=False, max_tokens=128, temperature=0, **options)
                    observation.record('classification', token_usage(result.usage))
                    if len(result.choices) != 1:
                        raise ValueError('invalid choices')
                    choice = result.choices[0]
                    message = choice.message
                    if (choice.index != 0 or choice.finish_reason != 'stop' or message.role != 'assistant'
                            or message.refusal or message.tool_calls or message.function_call):
                        raise ValueError('incomplete or unsupported classification')
                    return parse_decision(message.content)
        except Exception:
            # Cancellation (BaseException) propagates. No retries or unguarded fallback.
            raise AgentError('CLASSIFICATION_UNAVAILABLE',
                             '질문 주제를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.') from None
        finally:
            solid_llm._slots.release()

"""Opt-in live comparison driver. Run each source revision in a separate process.

Only synthetic fixtures are supported by this operator tool. Aggregate output is
written incrementally; --review prints synthetic answers for manual inspection,
never production conversation data. Credentials must be supplied at runtime.
Use an isolated source export as --source-root; it is imported, not modified.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--arm', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--facts-only', action='store_true')
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from app.schemas.assistant import ChatRequest
    from app.services.assistant.classifier import TopicClassifier
    from app.services.assistant.guarded import GuardedProvider
    from app.services.assistant.telemetry import Observation
    from app.core.config import settings
    from app.services.assistant.prompt import SYSTEM_PROMPT
    from app.services.assistant.policy import CLASSIFIER_PROMPT
    # Same evaluator for every revision, imported against that revision's provider.
    spec = importlib.util.spec_from_file_location('quality_evaluator', REPO/'scripts/evaluate_assistant_context.py')
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    logging.disable(logging.CRITICAL)
    factual_path=REPO/'tests/fixtures/assistant_quality_cases.json'
    prose_path=REPO/'tests/fixtures/assistant_prose_cases.json'
    cases=json.loads(factual_path.read_text())
    prose=json.loads(prose_path.read_text())
    report={'arm':args.arm,'model':settings.SOLID_LLM_MODEL,
            'answer_prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            'classifier_prompt_sha256':hashlib.sha256(CLASSIFIER_PROMPT.encode()).hexdigest(),
            'fixture_sha256':hashlib.sha256(factual_path.read_bytes()+prose_path.read_bytes()).hexdigest(),
            'answer_max_tokens':settings.ASSISTANT_MAX_TOKENS,'records':[]}
    def record(value):
        report['records'].append(value)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(value,ensure_ascii=False),flush=True)

    async def ask(identifier,question,history):
        observation=Observation()
        row={'id':identifier}
        class Classifier:
            async def classify(self, request, ignored):
                decision=await TopicClassifier().classify(request,observation)
                row['decision']=decision.value
                row['topics']=list(getattr(request,'_answer_topics',()))
                return decision
        request=ChatRequest(messages=history+[{'role':'user','content':question}],editor_source=cases[0]['editor_source'])
        request._execution_context=cases[0]['context']
        answer=''
        started=time.monotonic()
        try:
            async with asyncio.timeout(settings.ASSISTANT_TIMEOUT_SECONDS):
                events=[e async for e in GuardedProvider(classifier=Classifier()).stream(request)]
            answer=''.join(e['text'] for e in events if e['type']=='delta')
            row.update(characters=len(answer),stop_reason=events[-1].get('stop_reason'),
                       answer_usage=events[-1].get('usage',{}),
                       reference_match=events[-1].get('context')==request._execution_context['reference'])
        except Exception as error:
            row['error_type']=type(error).__name__
        row['classification_usage']=observation.usage.get('classification',{})
        row['seconds']=round(time.monotonic()-started,3)
        record(row)
        if args.review:
            print(json.dumps({'id':identifier,'synthetic_review':answer},ensure_ascii=False),flush=True)
        return answer, row

    async def run():
        for n in range(1,args.rounds+1):
            record({'round':n,'factual':await evaluator.evaluate(cases)})
        if args.facts_only: return
        for case in prose:
            await ask('fresh:'+case['id'],case['question'],[])
        history=[]
        for case in prose:
            # Preserve one conversation within the public 24k/20-message bounds.
            # Record trimming, rather than aborting on a verbose baseline.
            while history and sum(len(m['content']) for m in history)+len(case['question'])>24000:
                history=history[2:]
                record({'event':'history_trimmed','before':case['id']})
            answer,row=await ask('sequential:'+case['id'],case['question'],history)
            if answer and row.get('stop_reason')=='end_turn':
                history.extend([{'role':'user','content':case['question']},{'role':'assistant','content':answer[:8000]}])
        await ask('explicit-detail','첨부한 C 코드가 1부터 4까지 더하는 과정을 단계별로 자세히 설명하고, i와 sum의 값을 표로 정리해줘. 이것은 코드의 정적 분석이며 실제 실행 이력이 아니라는 점도 구분해줘.',[])
    asyncio.run(run())


if __name__=='__main__':
    main()

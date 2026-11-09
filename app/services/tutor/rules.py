"""Deterministic educational rules ported from FE tutorAnalysis.ts.

These are syntax hints, not a C parser or claims about actual compiled execution.
"""
import re
from app.schemas.tutor import ExplainItem, RuleExplanation


def explain(item: ExplainItem) -> RuleExplanation:
    if item.kind == 'c':
        return explain_c(item.text)
    result = explain_asm(item.text)
    if item.kind == 'crt':
        result.kind = 'crt'
        result.category = 'crt'
        result.title = 'C Runtime (CRT) 부트스트랩 코드'
        result.detail = '프로그램 시작 코드입니다. 실제 역할은 주변 명령어와 코드 매핑을 함께 확인해야 합니다. ' + result.detail
        if item.pc:
            result.detail = f'PC {item.pc}: ' + result.detail
    return result


def explain_c(raw: str) -> RuleExplanation:
    line = raw.strip()
    def out(category, title, summary, detail):
        return RuleExplanation(kind='c', category=category, title=title, summary=summary, detail=detail)
    if not line:
        return out('empty', '빈 줄', '내용이 없는 공백 라인입니다.', '별도의 실행 구문이 없습니다.')
    if line.startswith(('//', '/*', '*')):
        return out('comment', '주석', '개발자를 위한 설명입니다.', '주석은 직접 실행되지 않습니다. 여러 줄 주석은 주변 문맥 확인이 필요합니다.')
    if line.startswith('#'):
        return out('preprocessor', '전처리기', '컴파일 전 소스를 가공하는 지시문입니다.', '헤더 포함, 매크로 또는 조건부 컴파일에 사용됩니다.')
    match = re.search(r'\b(?:int|void|char|float|double|long|short)\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{?', line)
    if match:
        return out('function', '함수 선언/정의', f"'{match[1]}' 함수의 인터페이스 또는 시작입니다.", '함수 정의 시 필요한 스택 프레임과 레지스터 보존 코드는 ABI 및 최적화에 따라 달라집니다.')
    if re.match(r'^return\b', line):
        value = line[6:].rstrip(';').strip()
        return out('return', '반환문', f'값({value})을 반환합니다.' if value else '함수를 종료합니다.', '정수 반환값에는 보통 a0를 사용합니다. 복귀 및 레지스터 복원 방식은 생성된 ASM을 확인하세요.')
    for pattern, category, title, summary in [
        (r'^else\s+if\s*\(', 'else_if', '추가 조건문', '이전 조건이 거짓일 때 새 조건을 평가합니다.'),
        (r'^if\s*\(', 'if', '조건문', '조건의 참/거짓에 따라 실행 흐름을 선택합니다.'),
        (r'^else\b', 'else', '대체 분기', '앞선 조건이 거짓일 때 실행합니다.'),
        (r'^for\s*\(', 'for', '반복문', '초기화·조건·증감을 사용하는 반복문입니다.'),
        (r'^while\s*\(', 'while', '반복문', '조건이 참인 동안 반복합니다.'),
        (r'^do\b', 'do', '반복문', '본문 실행 뒤 반복 조건을 확인합니다.'),
        (r'^switch\s*\(', 'switch', '다중 분기', '값에 따라 실행할 구간을 선택합니다.'),
    ]:
        if re.match(pattern, line):
            return out(category, title, summary, '분기·점프·비교 명령어 등으로 번역될 수 있으며 실제 명령어는 최적화와 코드에 따라 달라집니다.')
    match = re.search(r'\b(?:int|char|short|long|float|double|unsigned)\s+([A-Za-z_]\w*)\s*=\s*([^;]+);', line)
    if match:
        return out('initialization', '변수 초기화', f"변수 '{match[1]}'에 '{match[2].strip()}'을 할당합니다.", '저장 위치는 변수의 범위와 최적화에 따라 레지스터·스택·데이터 영역 등이 될 수 있습니다.')
    if re.search(r'\b(?:int|char|short|long|float|double|unsigned)\s+[A-Za-z_]\w*\s*;', line):
        return out('declaration', '변수 선언', '변수를 선언합니다.', '저장 위치와 초기화 여부는 범위·저장 기간·최적화에 따라 달라집니다.')
    if re.match(r'^[A-Za-z_]\w*\s*(?:\+=|-=|\*=|/=|%=|=(?!=)|\+\+|--)', line):
        return out('assignment', '산술/대입 연산', '값을 계산해 변수에 반영합니다.', '로드·ALU 연산·저장 명령어 또는 레지스터 연산 등으로 구현될 수 있습니다.')
    match = re.search(r'([A-Za-z_]\w*)\s*\(.*\)\s*;', line)
    if match:
        return out('call', '함수 호출', f"'{match[1]}' 함수를 호출합니다.", '정수 인자는 보통 a0~a7로 전달하며, 필요한 경우 스택을 사용합니다. 인라인 최적화로 호출이 사라질 수도 있습니다.')
    if line in ('{', '}'):
        return out('scope', '코드 블록 경계', '블록의 시작입니다.' if line == '{' else '블록의 끝입니다.', '중괄호만으로 실제 스택 할당·해제를 확정할 수 없습니다.')
    return out('statement', 'C 실행 구문', 'C 소스 코드의 한 줄입니다.', '한 줄 패턴 기반 설명입니다. 정확한 의미는 주변 코드와 생성된 ASM을 확인하세요.')


def explain_asm(raw: str) -> RuleExplanation:
    text = raw.split('#', 1)[0].strip()
    tokens = text.split(None, 1)
    op = tokens[0].lower() if tokens else ''
    operands = re.sub(r',\s*', ', ', tokens[1]) if len(tokens) > 1 else ''
    parts = [p.strip() for p in operands.split(',')]
    rd, rs, third = (parts + ['?', '?', '?'])[:3]
    category, title = 'instruction', f'RISC-V 명령어 ({op})'
    summary, detail = f'{text} 명령어입니다.', '아직 상세 규칙이 없는 명령어입니다. ISA 명세와 실행 결과를 확인하세요.'
    if text.endswith(':'):
        category, title, summary, detail = 'label', '레이블', f'{text}은 주소를 나타내는 이름입니다.', '레이블 자체는 실행 명령어가 아닙니다.'
    elif text.startswith('.'):
        category, title, summary, detail = 'directive', '어셈블러 지시어', '섹션·심볼 등의 어셈블 설정입니다.', 'CPU가 직접 실행하지 않습니다.'
    elif op in ('lb', 'lbu', 'lh', 'lhu', 'lw'):
        category, title = 'load', '메모리 로드'
        summary = f'주소 {rs}의 값을 {rd}로 읽습니다.'
        detail = '주소와 접근 크기는 명령어에 따릅니다. 파이프라인에서는 메모리 읽기 후 레지스터 기록이 이뤄지며 실제 시점은 실행 이력을 확인하세요.'
    elif op in ('sb', 'sh', 'sw'):
        category, title = 'store', '메모리 저장'
        summary, detail = f'{rd}의 값을 주소 {rs}에 씁니다.', '기준 레지스터와 오프셋으로 주소를 계산합니다. 스택 접근인지 여부는 기준 주소에 따라 다릅니다.'
    elif op == 'addi' and rd in ('sp', 'x2') and rs in ('sp', 'x2'):
        try:
            amount = int(third, 0)
            category, title = 'stack', '스택 포인터 조정'
            summary = f'스택 포인터를 {amount}바이트 조정합니다.'
            detail = '음수 조정은 보통 공간 확보, 양수 조정은 보통 공간 반환에 사용됩니다.'
        except ValueError:
            pass
    elif op in ('add', 'addi', 'sub', 'mul', 'div', 'rem'):
        symbol = {'add': '+', 'addi': '+', 'sub': '-', 'mul': '*', 'div': '/', 'rem': '%'}[op]
        category, title, summary = 'arithmetic', '산술 연산', f'{rd} = {rs} {symbol} {third}'
        detail = '레지스터 또는 즉치값으로 연산합니다. mul은 하위 32비트, div/rem은 부호 있는 정수 연산입니다.'
    elif op in ('li', 'mv'):
        category, title, summary = 'pseudo', '의사 명령어', f'{rd}에 {rs} 값을 설정합니다.'
        detail = '실제 기계어는 즉치값·어셈블러에 따라 하나 이상의 기본 명령어로 확장됩니다.'
    elif op in ('beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu'):
        category, title, summary = 'branch', '조건 분기', f'{rd}와 {rs}를 비교해 조건 만족 시 {third}로 이동합니다.'
        detail = '실제 분기 여부와 플러시는 해당 사이클의 CORE 이벤트를 확인하세요.'
    elif op == 'auipc':
        category, title, summary, detail = 'address', 'PC 기준 주소 계산', f'{rd} = PC + ({rs} << 12)', 'PC 상대 주소 계산에 사용합니다. main 호출 여부는 주변 명령어를 확인해야 합니다.'
    elif op in ('jal', 'jalr', 'j', 'call', 'jr', 'ret'):
        category, title = 'control', '점프/호출/복귀'
        summary = f'{text}: 실행 흐름을 변경합니다.'
        detail = 'jal은 PC 상대, jalr은 레지스터 기준 주소로 이동합니다. 링크 대상이 x0이면 복귀 주소를 저장하지 않습니다. ret은 jalr x0, 0(ra)의 의사 명령어입니다.'
    elif op == 'ecall':
        category, title, summary, detail = 'environment', '환경 호출', '실행 환경에 처리를 요청합니다.', '지원 호출 번호와 의미는 시뮬레이터 규약에 따릅니다.'
    return RuleExplanation(kind='asm', category=category, title=title, summary=summary,
                           detail=detail, opcode=op, operands=operands)

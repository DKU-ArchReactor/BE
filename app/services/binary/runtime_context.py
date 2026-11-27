"""Function-level context for the bundled runtime, not execution observations."""

_MEMORY = {
    'malloc': (
        '사용하지 않는 힙 블록을 찾아 요청한 크기의 메모리를 확보합니다.',
        '크기를 16바이트 단위로 맞추고, 남는 공간이 충분하면 블록을 나눕니다. 확보한 공간의 주소를 반환하며 공간이 부족하거나 크기가 0이면 NULL을 반환합니다. 내용은 초기화하지 않습니다.'),
    'calloc': (
        '배열에 필요한 메모리를 확보하고 내용을 0으로 채웁니다.',
        '개수와 원소 크기를 검사한 뒤 malloc으로 공간을 확보하고 각 바이트를 0으로 만듭니다. 크기가 0이거나 확보할 수 없으면 NULL을 반환합니다.'),
    'realloc': (
        '기존 데이터가 유지되도록 할당 크기를 변경합니다.',
        '기존 블록이 충분하면 같은 주소를 사용합니다. 더 큰 공간이 필요하면 새 블록에 데이터를 복사하고 기존 블록을 해제합니다. 실패하면 NULL을 반환하며 기존 블록은 유지합니다. NULL 포인터는 새 할당으로, 크기 0은 해제로 처리합니다.'),
    'free': (
        '사용한 힙 블록을 다시 할당할 수 있는 상태로 돌려놓습니다.',
        '블록을 미사용으로 표시하고 이웃한 빈 블록을 합칩니다. 저장된 값을 지우는 작업은 아니므로 메모리 화면에는 이전 값이 남을 수 있습니다. 해제한 포인터로 다시 접근하면 안 됩니다. free(NULL)은 아무 작업도 하지 않습니다.'),
}


def runtime_context(source_file: str | None, function: str | None) -> dict | None:
    if source_file == 'allocator.c' and function in _MEMORY:
        summary, detail = _MEMORY[function]
        return {'function': function, 'label': f'{function} 내부', 'summary': summary,
                'detail': detail + ' 힙은 관리 정보를 포함해 4 KiB입니다. 이 설명은 함수 전체의 역할이며, 선택한 명령어 하나가 모든 작업을 수행한다는 뜻은 아닙니다.'}
    if source_file == 'start.S' and function == '_start':
        return {'function': '_start', 'label': '시작·종료 코드',
                'summary': '사용자가 작성한 main을 호출하고, main이 반환하면 시뮬레이션을 종료합니다.',
                'detail': 'call main으로 제어를 넘깁니다. main이 반환하면 a7에 종료 번호 10을 넣고 ecall로 CORE에 종료를 알립니다. main의 반환값은 a0에서 확인합니다. 사용자가 작성한 C 줄과 직접 연결되지 않는 실행 지원 코드입니다.'}
    return None

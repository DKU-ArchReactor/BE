def process_binary(binary: bytes) -> bytes:
    """컴파일 완료된 ELF 바이너리에 대한 후처리 훅.

    현재는 패스스루(입력 그대로 반환). 추후 정적 분석/메타데이터 추출,
    시뮬레이션용 변환 등이 이 모듈로 추가될 자리.
    """
    return binary

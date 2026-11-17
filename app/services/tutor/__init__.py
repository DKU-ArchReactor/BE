"""Optional remote explanations; compiler and CORE results survive tutor outages."""
from fastapi import HTTPException
from app.services import tutor_client


def compile_explanations(source, lang, assembly):
    try:
        return tutor_client.compiled_source(source, lang, assembly)
    except HTTPException:
        return None


def simulation_explanations(result, *, elf_bytes=None, source='', source_file=None):
    try:
        return tutor_client.analyze_result(result, elf_bytes=elf_bytes, source=source, source_file=source_file)
    except HTTPException:
        return None

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.build import BuildCompileRequest


def test_content_with_lang_is_valid():
    req = BuildCompileRequest(
        content="int main(){return 0;}", lang="c", compiler_opt="-O2"
    )
    assert req.file_id is None
    assert req.content == "int main(){return 0;}"
    assert req.lang == "c"


def test_file_id_only_is_valid():
    req = BuildCompileRequest(file_id=uuid.uuid4(), compiler_opt="-O0")
    assert req.content is None
    assert req.lang is None


def test_both_file_id_and_content_rejected():
    with pytest.raises(ValidationError):
        BuildCompileRequest(
            file_id=uuid.uuid4(),
            content="x",
            lang="c",
            compiler_opt="",
        )


def test_neither_file_id_nor_content_rejected():
    with pytest.raises(ValidationError):
        BuildCompileRequest(compiler_opt="")


def test_content_without_lang_rejected():
    with pytest.raises(ValidationError):
        BuildCompileRequest(content="x", compiler_opt="")

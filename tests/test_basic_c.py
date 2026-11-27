"""Exercise real parsing and both compile entry points without a compiler or AWS."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.deps import get_current_user_optional
from app.routers import build
from app.services import build_service
from app.services.basic_c import validate_basic_c
from app.services.assistant.code_policy import C_EXAMPLE_POLICY
from app.services.assistant.prompt import SYSTEM_PROMPT


@pytest.mark.parametrize('source', [
    'int x; int main(void){ x=2; return x; }',
    'volatile int x=3; int main(void){ x++; return x; }',
    'int main(void){ return 0; } volatile int tail[2]={1,2};',
    'static volatile int a[2]={2,3}; int main(void){return a[0]+a[1];}',
    '#include <stdlib.h>\nint main(void){int *p=malloc(2*sizeof(int)); if(!p)return 1; p[0]=7; int n=p[0]; free(p); return n;}',
    'int main(void){size_t n=3; int *p=calloc(n,sizeof(int)); free(p); return 0;}',
    '#include <stdlib.h> // comment\nint main(void){void *p=NULL; p=realloc(p,16); free(p); return 0;}',
    'int main(void) { return 0; }',
    'int main() { int a[2+1] = {1,2,3}; int sum=0; for(int i=0;i<3;i++) sum+=a[i]; return sum; }',
    'int main(void) { char text[] = "#include <stdio.h> printf( hi )"; return text[0]; }',
    '// #include <stdio.h>\nint main(void) { /* printf(hi); */ return 0; }',
    'int main(void) { volatile int x=3; while(x>1) x--; if(x) return 1; else return 0; }',
    'int main(void) { char quote=\'"\'; char slash=\'/\'; return quote+slash; }',
    '// ignored \\\n#include <stdio.h>\nint main(void) { return 0; }',
])
def test_allowed_examples_and_non_code_text(source):
    assert validate_basic_c(source) == []


@pytest.mark.parametrize('source,code,line', [
    ('#include <stdio.h>\nint main(void){return 0;}', 'PREPROCESSOR_NOT_ALLOWED', 1),
    ('/* note */\n#define X 2\nint main(void){return X;}', 'PREPROCESSOR_NOT_ALLOWED', 2),
    ('%:include <stdio.h>\nint main(void){return 0;}', 'PREPROCESSOR_NOT_ALLOWED', 1),
    ('??=include <stdio.h>\nint main(void){return 0;}', 'PREPROCESSOR_NOT_ALLOWED', 1),
    ('int main(void){\n printf("hello");\nreturn 0;}', 'FUNCTION_CALL_NOT_ALLOWED', 2),
    ('int main(void){\n prin\\\ntf("hello");return 0;}', 'FUNCTION_CALL_NOT_ALLOWED', 2),
    ('int main(void){return (printf)("hello");}', 'FUNCTION_CALL_NOT_ALLOWED', 1),
    ('int main(void){return main();}', 'FUNCTION_CALL_NOT_ALLOWED', 1),
    ('int main(void){ return (*p)(); }', 'FUNCTION_CALL_NOT_ALLOWED', 1),
    ('int helper(void){return 1;}\nint main(void){return 0;}', 'MAIN_ONLY', 1),
    ('int x;\nint helper(void){return 0;}', 'MAIN_ONLY', 2),
    ('int *p=malloc(4); int main(void){return 0;}', 'GLOBAL_INITIALIZER_CALL', 1),
    ('float x; int main(void){return 0;}', 'INTEGER_ONLY', 1),
    ('extern int x; int main(void){return 0;}', 'STORAGE_NOT_SUPPORTED', 1),
    ('int helper(void); int main(void){return 0;}', 'TYPE_NOT_SUPPORTED', 1),
    ('int (*fn)(void); int main(void){return 0;}', 'TYPE_NOT_SUPPORTED', 1),
    ('#include "stdlib.h"\nint main(void){return 0;}', 'PREPROCESSOR_NOT_ALLOWED', 1),
    ('#include <stdlib.h>\n#define N 2\nint main(void){return 0;}', 'PREPROCESSOR_NOT_ALLOWED', 2),
    ('int main(void){return abs(-1);}', 'FUNCTION_CALL_NOT_ALLOWED', 1),
    ('int main(int argc, char **argv){return 0;}', 'MAIN_SIGNATURE', 1),
    ('void main(void){}', 'MAIN_SIGNATURE', 1),
    ('int main(void){ extern int x; return x; }', 'STORAGE_NOT_SUPPORTED', 1),
    ('int main(void){ int f(void); return 0; }', 'TYPE_NOT_SUPPORTED', 1),
    ('int main(void){ int (*f)(void); return 0; }', 'TYPE_NOT_SUPPORTED', 1),
    ('int main(void){ int n=3; int a[n]; return 0; }', 'FIXED_ARRAY_ONLY', 1),
    ('int main(void){ double x=1.2; return 0; }', 'INTEGER_ONLY', 1),
    ('int main(void){ return (int)1.2; }', 'INTEGER_ONLY', 1),
    ('int main(void){ asm volatile("ecall"); return 0; }', 'INVALID_C_SYNTAX', 1),
    ('int main(void){\nreturn ;', 'INVALID_C_SYNTAX', 1),
])
def test_rejects_unsupported_code_with_location(source, code, line):
    diagnostic, = validate_basic_c(source)
    assert diagnostic['code'] == code
    assert diagnostic['line'] == line
    assert diagnostic['column'] >= 1


def test_size_limit_and_deep_expression_do_not_crash():
    assert validate_basic_c('가' * 22000)[0]['code'] == 'SOURCE_TOO_LARGE'
    source = 'int main(void){return ' + '(' * 2000 + '0' + ')' * 2000 + ';}'
    assert validate_basic_c(source) == []


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(build.router)
    db = Mock()
    user = SimpleNamespace(user_id='owner')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_optional] = lambda: user
    file = SimpleNamespace(file_id=uuid.uuid4(), lang='c', content='#include <stdio.h>\nint main(void){return 0;}')
    monkeypatch.setattr(build.file_service, 'get_file', lambda *args: file)
    compiler = Mock(side_effect=AssertionError('invalid C must not start a compiler'))
    upload = Mock(side_effect=AssertionError('invalid C must not upload artifacts'))
    token = Mock(side_effect=AssertionError('invalid C must not issue a token'))
    monkeypatch.setattr(build_service, '_run', compiler)
    monkeypatch.setattr(build_service, 'upload_bytes', upload)
    monkeypatch.setattr(build, 'create_simulation_token', token)
    return TestClient(app), db, file, compiler, upload, token


def test_validation_is_read_only_and_shared_by_saved_and_direct_compile(api):
    client, db, file, compiler, upload, token = api
    validated = client.post('/api/v1/build/validate-c', json={'content': file.content})
    assert validated.status_code == 200
    assert validated.json()['valid'] is False
    assert validated.json()['policy'] == 'basic-c-v1'
    assert db.mock_calls == []
    for source in ({'content': file.content, 'lang': 'c'}, {'file_id': str(file.file_id)}):
        response = client.post('/api/v1/build/compile', json={**source, 'compiler_opt': '-O0'})
        assert response.status_code == 201
        data = response.json()
        assert data['status'] == 'failed'
        assert data['diagnostics'] == validated.json()['diagnostics']
        assert data['binary_url'] is None and data['simulation_token'] is None
        assert '1행' in data['log']
    compiler.assert_not_called()
    upload.assert_not_called()
    token.assert_not_called()


def test_validation_accepts_basic_program_and_limits_input(api):
    client = api[0]
    assert client.post('/api/v1/build/validate-c', json={'content': 'int main(void){return 0;}'}).json()['valid']
    assert client.post('/api/v1/build/validate-c', json={'content': 'a' * 65536}).status_code == 422


@pytest.mark.parametrize('lang,profile', [('c', 'native'), ('asm', 'rv32im')])
def test_other_profiles_bypass_policy(monkeypatch, lang, profile):
    monkeypatch.setattr(build_service, 'validate_basic_c', Mock(side_effect=AssertionError('unexpected policy')))
    monkeypatch.setattr(build_service, '_run', lambda cmd: SimpleNamespace(returncode=1, stdout='', stderr='compiler reached'))
    assert 'compiler reached' in build_service.compile_source('input', lang, '', profile).log


def test_ai_prompt_example_passes_the_actual_policy():
    assert C_EXAMPLE_POLICY in SYSTEM_PROMPT
    source = C_EXAMPLE_POLICY.split('```c\n')[1].split('```')[0]
    assert validate_basic_c(source) == []

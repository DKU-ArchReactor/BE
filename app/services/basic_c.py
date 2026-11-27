"""Basic C admission policy. Parses source without invoking a preprocessor/compiler.

This limits the teaching language; it is not an execution security sandbox.
"""
import re

from pycparser import c_ast, c_parser
from pycparser.plyparser import ParseError

MAX_SOURCE_BYTES = 65535
MEMORY_FUNCTIONS = {'malloc', 'calloc', 'realloc', 'free'}
_LEXEMES = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')


def validate_basic_c(source: str) -> list[dict]:
    """Return the first actionable diagnostic, with original source coordinates."""
    def diagnostic(code, message, line=1, column=1):
        return [{'code': code, 'message': message, 'line': line, 'column': column}]

    if len(source.encode('utf-8')) > MAX_SOURCE_BYTES:
        return diagnostic('SOURCE_TOO_LARGE', 'C 코드는 UTF-8 기준 65,535바이트까지 검사할 수 있습니다.')

    # C removes escaped newlines before recognizing comments/tokens. Track physical
    # coordinates so spliced lines cannot hide a call or move the reported location.
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    positions = []
    text = []
    line = column = 1
    i = 0
    while i < len(source):
        if source.startswith('\\\n', i):
            i += 2
            line, column = line + 1, 1
            continue
        positions.append((line, column))
        text.append(source[i])
        if source[i] == '\n':
            line, column = line + 1, 1
        else:
            column += 1
        i += 1
    text = ''.join(text)
    positions.append((line, column))
    blank = lambda value: ''.join('\n' if c == '\n' else ' ' for c in value)
    # Preserve literals for parsing, but ignore them when detecting directives.
    parsed = _LEXEMES.sub(lambda m: blank(m[0]) if m[0].startswith('/') else m[0], text)
    masked = _LEXEMES.sub(lambda m: blank(m[0]), text)
    # Only our bundled stdlib.h is available. Never run a user preprocessor.
    # Detect include lines in comment-stripped text, not masked literals.
    for include in re.finditer(r'(?m)^[ \t]*#[ \t]*include[ \t]*<stdlib\.h>[ \t]*$', parsed):
        start, end = include.span()
        masked = masked[:start] + blank(masked[start:end]) + masked[end:]
        parsed = parsed[:start] + blank(parsed[start:end]) + parsed[end:]
    directive = re.search(r'#|%:|\?\?=', masked)
    if directive:
        return diagnostic('PREPROCESSOR_NOT_ALLOWED',
                          '#include <stdlib.h>만 허용합니다. 다른 헤더와 #define 등 전처리 지시문은 지원하지 않습니다.',
                          *positions[directive.start()])

    starts = [0] + [m.end() for m in re.finditer('\n', parsed)]

    def location(coord):
        if coord is None:
            return 1, 1
        index = starts[min(coord.line - 1, len(starts) - 1)] + max((coord.column or 1) - 1, 0)
        return positions[min(index, len(positions) - 1)]

    def fail(node, code, message):
        return diagnostic(code, message, *location(node.coord))

    try:
        # A trusted typedef supplies the bundled header's size_t without reading
        # any headers. Keep it on the same line and correct first-line columns.
        prelude = 'typedef unsigned int size_t; '
        tree = c_parser.CParser().parse(prelude + parsed, filename='source.c')
        tree.ext.pop(0)
        nodes = [tree]
        while nodes:
            node = nodes.pop()
            if node.coord and node.coord.line == 1:
                node.coord.column = max(1, node.coord.column - len(prelude))
            nodes.extend(child for _, child in node.children())
    except ParseError as error:
        match = re.search(r'source\.c:(\d+):(\d+):', str(error))
        row, col = (int(match[1]), int(match[2])) if match else (1, 1)
        if match and row == 1:
            col = max(1, col - len(prelude))
        index = starts[min(row - 1, len(starts) - 1)] + col - 1
        return diagnostic('INVALID_C_SYNTAX',
                          'C 문법을 확인하세요. int main(void) 안에 정수 변수·배열·조건문·반복문을 작성하고, 인라인 어셈블리는 사용하지 마세요.',
                          *positions[min(index, len(positions) - 1)])
    except RecursionError:
        return diagnostic('SOURCE_TOO_COMPLEX', '코드의 중첩이 너무 깊습니다. 수식과 블록을 단순하게 나누세요.')

    functions = [node for node in tree.ext if isinstance(node, c_ast.FuncDef)]
    if len(functions) != 1 or functions[0].decl.name != 'main':
        offending = next((node for node in functions if node.decl.name != 'main'), tree)
        return fail(offending, 'MAIN_ONLY', '함수는 int main(void) 하나만 작성하세요. 전역 변수는 허용하지만 별도 함수는 지원하지 않습니다.')
    main = functions[0]
    globals_ = [node for node in tree.ext if node is not main]
    for node in globals_:
        if not isinstance(node, c_ast.Decl) or not node.name:
            return fail(node, 'TYPE_NOT_SUPPORTED', '전역에는 정수형 변수·고정 크기 배열·포인터를 선언하세요.')
        initializers = [node.init] if node.init else []
        while initializers:
            initializer = initializers.pop()
            if isinstance(initializer, c_ast.FuncCall):
                return fail(initializer, 'GLOBAL_INITIALIZER_CALL', '전역 변수의 동적 할당은 선언 후 main 안에서 수행하세요.')
            initializers.extend(child for _, child in initializer.children())
    function = main.decl.type
    result_type = function.type
    parameters = function.args.params if function.args else []
    void_parameters = (len(parameters) == 1 and isinstance(parameters[0], c_ast.Typename)
                       and isinstance(parameters[0].type, c_ast.TypeDecl)
                       and isinstance(parameters[0].type.type, c_ast.IdentifierType)
                       and parameters[0].type.type.names == ['void'])
    if (not isinstance(result_type, c_ast.TypeDecl)
            or not isinstance(result_type.type, c_ast.IdentifierType)
            or result_type.type.names != ['int'] or main.decl.storage or main.decl.funcspec
            or (parameters and not void_parameters) or main.param_decls):
        return fail(main.decl, 'MAIN_SIGNATURE', '진입점은 인자 없는 int main(void)로 작성하세요.')

    # Iterative traversal also bounds validation of very deeply nested ASTs.
    # Global declarations must pass the same type, initializer and array checks;
    # accepting their presence must not bypass restrictions on types or calls.
    global_nodes = set(globals_)
    pending = [main.body, *reversed(globals_)]
    while pending:
        node = pending.pop()
        if isinstance(node, c_ast.FuncCall) and not (isinstance(node.name, c_ast.ID) and node.name.name in MEMORY_FUNCTIONS):
            return fail(node, 'FUNCTION_CALL_NOT_ALLOWED',
                        '함수 호출은 malloc·calloc·realloc·free만 지원합니다. 입출력·사용자 함수·간접 호출은 지원하지 않습니다.')
        if isinstance(node, (c_ast.FuncDecl, c_ast.Typedef, c_ast.Struct, c_ast.Union, c_ast.Enum)):
            return fail(node, 'TYPE_NOT_SUPPORTED', '정수형 변수·배열·포인터를 사용하세요. 함수 선언·함수 포인터·사용자 정의 자료형은 지원하지 않습니다.')
        if isinstance(node, c_ast.Decl) and node.storage and not (node in global_nodes and node.storage == ['static']):
            return fail(node, 'STORAGE_NOT_SUPPORTED', 'static은 전역 변수에만 사용할 수 있습니다. extern 등 외부 선언은 지원하지 않습니다.')
        if isinstance(node, c_ast.IdentifierType) and (
                set(node.names) - {'char', 'short', 'int', 'long', 'signed', 'unsigned', '_Bool', 'void', 'size_t'}
                or node.names.count('long') > 1):
            return fail(node, 'INTEGER_ONLY', '32비트 이하 정수형을 사용하세요. 실수형과 long long은 지원하지 않습니다.')
        if isinstance(node, c_ast.Constant) and ('float' in node.type or 'double' in node.type or 'long long' in node.type):
            return fail(node, 'INTEGER_ONLY', '32비트 이하 정수 상수를 사용하세요.')
        if isinstance(node, c_ast.ArrayDecl):
            dimensions = [node.dim] if node.dim is not None else []
            while dimensions:
                dimension = dimensions.pop()
                if not isinstance(dimension, (c_ast.Constant, c_ast.UnaryOp, c_ast.BinaryOp)) or (
                        isinstance(dimension, c_ast.UnaryOp) and dimension.op not in {'+', '-', '~', '!'}):
                    return fail(node, 'FIXED_ARRAY_ONLY', '배열 크기는 정수 상수식으로 지정하세요. 가변 길이 배열은 지원하지 않습니다.')
                dimensions.extend(child for _, child in dimension.children())
        pending.extend(child for _, child in reversed(list(node.children())))
    return []

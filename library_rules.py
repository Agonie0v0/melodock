"""Bounded tag expressions shared by batch edits and archive templates."""
import ast
import re
import string
import unicodedata
from functools import lru_cache
from pathlib import Path

import local_library

ALIASES = {'albumartist': 'album_artist', 'tracknumber': 'track_number', 'discnumber': 'disc_number'}
VARIABLES = {*local_library.TAG_FIELDS, *ALIASES, 'first_artist', 'first_artist_letter', 'filename',
             'file_song_name', 'parent_path', 'parent_parent_path', 'year', 'counter', 'null', 'lyrics', 'ext'}
METHODS = {'strip', 'lstrip', 'rstrip', 'replace', 'split', 'lower', 'upper', 'title', 'zfill'}


def expression(text, values):
    if len(text) > 1000:
        raise ValueError('变量表达式过长')
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        raise ValueError('变量表达式格式错误') from None
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('变量表达式过于复杂')

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in VARIABLES:
            value = values.get(node.id, '')
            if isinstance(value, str) and len(value) > 10000:
                raise ValueError('变量内容超过 10000 字符')
            return value
        if isinstance(node, ast.Constant) and type(node.value) in {str, int, bool}:
            if isinstance(node.value, int) and abs(node.value) > 1000:
                raise ValueError('表达式数字应在 -1000 到 1000 内')
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return visit(node.left) + visit(node.right)
        if isinstance(node, ast.BoolOp):
            result = ''
            for child in node.values:
                result = visit(child)
                if isinstance(node.op, ast.Or) and result or isinstance(node.op, ast.And) and not result:
                    break
            return result
        if isinstance(node, ast.IfExp):
            return visit(node.body if visit(node.test) else node.orelse)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not visit(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            return -visit(node.operand)
        if isinstance(node, ast.Subscript):
            value, index = visit(node.value), visit(node.slice)
            if isinstance(value, (str, list)) and type(index) is int:
                return value[index] if -len(value) <= index < len(value) else ''
        if isinstance(node, ast.Call) and not node.keywords and len(node.args) <= 3:
            args = [visit(arg) for arg in node.args]
            if isinstance(node.func, ast.Name) and node.func.id in {'str', 'int'} and len(args) == 1:
                return str(args[0]) if node.func.id == 'str' else int(args[0])
            if isinstance(node.func, ast.Attribute) and node.func.attr in METHODS:
                value = visit(node.func.value)
                if isinstance(value, str):
                    if node.func.attr == 'replace' and len(args) >= 2 and all(isinstance(arg, str) for arg in args[:2]):
                        count = value.count(args[0]) if args[0] else len(value) + 1
                        if len(args) == 3 and type(args[2]) is int and args[2] >= 0: count = min(count, args[2])
                        if len(value) + count * (len(args[1]) - len(args[0])) > 10000:
                            raise ValueError('变量结果过长')
                    result = getattr(value, node.func.attr)(*args)
                    if len(result) > 10000:
                        raise ValueError('变量结果过长')
                    return result
        raise ValueError('不支持的表达式；可使用标签变量、条件、拼接和常用字符串方法')
    try:
        return str(visit(tree))
    except (TypeError, IndexError, AttributeError, OverflowError):
        raise ValueError('变量表达式的类型或参数无效') from None


def render(template, values, format_value=str):
    # Expressions are interpreted through a fixed AST allowlist, never Python eval.
    expressions = {}
    def substitute(match):
        key = '__expression_' + str(len(expressions))
        expressions[key] = expression(match[1], values)
        return '{' + key + '}'
    value = re.sub(r'\$\{([^{}]+)\}', substitute, template)
    if '${' in value:
        raise ValueError('变量表达式括号未闭合或包含嵌套括号')
    parts = []
    try:
        for literal, field, spec, conversion in string.Formatter().parse(value):
            parts.append(literal)
            if field is not None:
                if field not in VARIABLES | expressions.keys() or spec or conversion:
                    raise ValueError('模板包含不支持的变量')
                parts.append(format_value(expressions[field] if field in expressions else values.get(field, '')))
    except (KeyError, ValueError):
        raise ValueError('模板格式无效或包含不支持的变量') from None
    result = ''.join(parts)
    if len(result) > 10000:
        raise ValueError('模板结果过长')
    return result


def extract(template, stem):
    parts, fields = [], []
    for literal, key, spec, conversion in string.Formatter().parse(template.replace('${', '{')):
        if key is not None:
            key = ALIASES.get(key, key)
            if key not in local_library.TAG_FIELDS or key in fields or spec or conversion:
                raise ValueError('提取模板应使用不重复的标签变量')
            if parts and parts[-1][1] is not None and not literal:
                raise ValueError('提取变量之间必须有固定分隔符')
            fields.append(key)
        parts.append((literal, key))
    if not fields:
        raise ValueError('提取模板至少包含一个标签变量')
    position, result = 0, {}
    for i, (literal, key) in enumerate(parts):
        if not stem.startswith(literal, position):
            raise ValueError('文件名不符合提取模板')
        position += len(literal)
        if key is None:
            continue
        separator = parts[i + 1][0] if i + 1 < len(parts) else ''
        end = stem.find(separator, position) if separator else len(stem)
        if i + 1 == len(parts) - 1 and parts[-1][1] is None and stem.endswith(separator):
            end = len(stem) - len(separator)
        if end <= position:
            raise ValueError('文件名不符合提取模板')
        result[key], position = stem[position:end].strip(), end
    if position != len(stem):
        raise ValueError('文件名不符合提取模板')
    return result


@lru_cache(maxsize=2)
def chinese_converter(style):
    from opencc import OpenCC
    return OpenCC('t2s' if style == 'simplified' else 's2t')


def variables(path, tags, counter=1, lyrics=''):
    path = Path(path)
    first = re.split(r'\s*[,，/;&、]\s*', tags.get('artist') or '')[0]
    from pypinyin import lazy_pinyin
    letter = (lazy_pinyin(first[:1])[0] if first else '#')[:1].upper()
    return {**dict.fromkeys(VARIABLES, ''), **tags,
            **{alias: tags.get(key, '') for alias, key in ALIASES.items()},
            'first_artist': first, 'first_artist_letter': letter,
            'year': (tags.get('date') or '')[:4], 'counter': str(counter), 'null': '', 'lyrics': lyrics,
            'filename': path.name, 'file_song_name': path.stem, 'parent_path': path.parent.name,
            'parent_parent_path': path.parent.parent.name, 'ext': path.suffix.lstrip('.')}


def transform(value, *, find='', replacement='', chinese='none', repair=False):
    value = str(value or '')
    if repair:
        # Only reverse a lossless UTF-8-as-Latin1 mistake; never replace undecodable bytes.
        try:
            repaired = value.encode('latin1').decode('utf-8')
            if repaired != value:
                value = repaired
        except (UnicodeError, ValueError):
            pass
    value = unicodedata.normalize('NFC', re.sub(r'\s+', ' ', value).strip())
    if find:
        value = value.replace(find, replacement)
    if chinese != 'none':
        value = chinese_converter(chinese).convert(value)
    return value

import datetime
import io
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from shlex import shlex
from types import GeneratorType
from xml.etree import ElementTree

from dateutil.parser import parse as parse_flexible_date
from trytond.modules.xgettext import _
from trytond.pool import Pool
from trytond.pyson import PYSONDecoder
from trytond.tools import timezone
from trytond.transaction import Transaction

from .state import decode_value


OPERATORS = ('!=', '<=', '>=', '=', '!', '<', '>')
COMMON_SEARCH_FIELDS = (
    ('id', 'ID', 'integer'),
    ('create_uid', 'Created by', 'many2one'),
    ('create_date', 'Created at', 'datetime'),
    ('write_uid', 'Modified by', 'many2one'),
    ('write_date', 'Modified at', 'datetime'),
    )


def common_search_title(title):
    return {
        'ID': _('ID'),
        'Created by': _('Created by'),
        'Created at': _('Created at'),
        'Modified by': _('Modified by'),
        'Modified at': _('Modified at'),
        }[title]


class SearchLexer(shlex):
    """Sao's lexer for the human-readable domain language."""

    def __init__(self, value):
        super().__init__(io.StringIO(value), posix=True)
        self.commenters = ''
        self.quotes = '"'

        class WordCharacters:

            def __contains__(self, character):
                return character not in {
                    ':', '>', '<', '=', '!', '"', ';', '(', ')'}

        self.wordchars = WordCharacters()


def is_generator(value):
    return isinstance(value, (GeneratorType, type(iter([])), type(iter(()))))


def recursive_list(value):
    if is_generator(value) or isinstance(value, list):
        return [recursive_list(item) for item in value]
    return value


def simplify(value):
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], list):
            return simplify(value[0])
        if (len(value) == 2 and value[0] in ('AND', 'OR')
                and isinstance(value[1], list)):
            return simplify(value[1])
        if (len(value) == 3 and value[0] in ('AND', 'OR')
                and isinstance(value[1], list)
                and value[0] == value[1][0]):
            value = simplify(value[1]) + [value[2]]
        return [simplify(item) for item in value]
    return value


def group_operator(tokens):
    try:
        current = next(tokens)
    except StopIteration:
        return
    for following in tokens:
        if following == '=' and current and current + following in OPERATORS:
            yield current + following
            current = None
        else:
            if current is not None:
                yield current
            current = following
    if current is not None:
        yield current


def parenthesize(tokens):
    for token in tokens:
        if token == '(':
            yield iter(list(parenthesize(tokens)))
        elif token == ')':
            break
        else:
            yield token


def operatorize(tokens, operator):
    markers = {
        'or': ('|', ('|',)),
        'and': ('&', ('&',)),
        }[operator]
    try:
        current = next(tokens)
        while current in markers:
            current = next(tokens)
    except StopIteration:
        return
    if is_generator(current):
        current = operatorize(current, operator)
    following = None
    for following in tokens:
        if is_generator(following):
            following = operatorize(following, operator)
        if following in markers:
            try:
                following = next(tokens)
                while following in markers:
                    following = next(tokens)
                if is_generator(following):
                    following = operatorize(following, operator)
                current = iter([operator.upper(), current, following])
            except StopIteration:
                if current not in markers:
                    yield iter([operator.upper(), current])
                    current = None
            following = None
        else:
            if current not in markers:
                yield current
            current = following
    if following is not None and following not in markers:
        yield following
    elif current is not None and current not in markers:
        yield current


def likify(value, escape='\\'):
    if not value:
        return '%'
    escaped = value.replace(escape + '%', '').replace(escape + '_', '')
    if '%' in escaped or '_' in escaped:
        return value
    return '%' + value + '%'


def is_full_text(value, escape='\\'):
    if not isinstance(value, str):
        return False
    escaped = value
    if escaped.startswith('%') and escaped.endswith('%'):
        escaped = escaped[1:-1]
    escaped = escaped.replace(escape + '%', '').replace(escape + '_', '')
    return (
        '%' not in escaped and '_' not in escaped
        and value.startswith('%') and value.endswith('%'))


def is_like(value, escape='\\'):
    if not isinstance(value, str):
        return False
    escaped = value.replace(escape + '%', '').replace(escape + '_', '')
    return '%' in escaped or '_' in escaped


def unescape(value, escape='\\'):
    return value.replace(escape + '%', '%').replace(escape + '_', '_')


def quote(value, empty=False):
    if not isinstance(value, str):
        return value
    if empty and value == '':
        return '""'
    value = value.replace('\\', '\\\\').replace('"', '\\"')
    if any(test in value for test in (':', ' ', '(', ')') + OPERATORS):
        return '"%s"' % value
    return value


def default_operator(field):
    if field.get('type') in {
            'char', 'text', 'many2one', 'many2many', 'one2many',
            'reference', 'one2one'}:
        return 'ilike'
    if field.get('type') == 'multiselection':
        return 'in'
    return '='


def negate_operator(operator):
    return {
        'ilike': 'not ilike',
        '=': '!=',
        'in': 'not in',
        }.get(operator)


def valid_selection(field):
    selection = field.get('selection') or []
    if not isinstance(selection, (list, tuple)):
        return []
    return [
        (entry[0], entry[1])
        for entry in selection
        if isinstance(entry, (list, tuple)) and len(entry) == 2
        ]


def date_format(context):
    locale = context.get('locale') or {}
    return (
        context.get('date_format')
        or locale.get('date')
        or '%Y-%m-%d')


def time_format(field):
    format_ = field.get('format') or '%H:%M:%S'
    if isinstance(format_, str):
        try:
            decoded = PYSONDecoder({}).decode(format_)
            if isinstance(decoded, str):
                format_ = decoded
        except Exception:
            pass
    return format_


def parse_date(value, format_):
    try:
        return datetime.datetime.strptime(value, format_)
    except (TypeError, ValueError):
        sample = datetime.date(1988, 7, 16).strftime(format_)
        day_first = sample.find('16') == 0
        month_position = sample.find('7')
        month_first = 0 <= month_position <= 1
        return parse_flexible_date(
            value, dayfirst=day_first,
            yearfirst=not day_first and not month_first,
            ignoretz=True)


def parse_number(value, context, decimal=False):
    locale_ = context.get('locale') or {}
    thousands = locale_.get('thousands_sep') or ''
    decimal_point = locale_.get('decimal_point') or '.'
    value = str(value).replace(' ', '')
    if thousands:
        value = value.replace(thousands, '')
    if decimal_point != '.':
        value = value.replace(decimal_point, '.')
    return Decimal(value) if decimal else float(value)


def to_server_datetime(value, context):
    zone = context.get('timezone')
    if zone and value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.get_tzinfo(zone)).astimezone(
                timezone.UTC).replace(tzinfo=None)
    return value


def to_local_datetime(value, context):
    zone = context.get('timezone')
    if zone and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.UTC).astimezone(
            timezone.get_tzinfo(zone)).replace(tzinfo=None)
    return value


def timedelta_converter(field, context):
    converter = context.get(field.get('converter')) or {}
    if converter:
        return converter
    return {
        's': 1, 'm': 60, 'h': 3600, 'd': 86400,
        'w': 604800, 'M': 2592000, 'Y': 31536000,
        }


def parse_timedelta(value, field, context):
    if not value:
        return None
    converter = timedelta_converter(field, context)
    seconds = 0
    for part in str(value).split():
        if ':' in part:
            for amount, unit in zip(part.split(':'), ('h', 'm', 's')):
                try:
                    seconds += abs(parse_number(amount, context)) * converter[unit]
                except (ValueError, InvalidOperation):
                    pass
            continue
        for unit in ('Y', 'M', 'w', 'd', 'h', 'm', 's'):
            if part.endswith(unit):
                try:
                    seconds += abs(parse_number(
                            part[:-len(unit)], context)) * converter[unit]
                except (ValueError, InvalidOperation):
                    pass
                break
        else:
            try:
                seconds += abs(parse_number(part, context))
            except (ValueError, InvalidOperation):
                pass
    if '-' in str(value):
        seconds *= -1
    return datetime.timedelta(seconds=seconds)


def convert_value(field, value, context):
    type_ = field.get('type')
    if type_ == 'boolean':
        if not isinstance(value, str):
            return None
        tests = {
            '1', 't', 'true', 'y', 'yes', 's', 'si', 'sí',
            str(_('True')).casefold(),
            str(_('Yes')).casefold(),
            }
        test = value.casefold()
        return any(candidate.startswith(test) for candidate in tests)
    if type_ in {'float', 'integer', 'numeric'}:
        factor = Decimal(str(field.get('factor', 1) or 1))
        try:
            result = parse_number(value, context, decimal=True) / factor
        except (ValueError, InvalidOperation, TypeError):
            return None
        return int(result) if type_ == 'integer' else result
    if type_ in {'selection', 'multiselection', 'reference'}:
        if type_ == 'reference' and value == '':
            return None
        if isinstance(value, str):
            for key, text in valid_selection(field):
                if value.casefold() == str(text).casefold():
                    return key
        return value
    if type_ in {'datetime', 'timestamp'}:
        if not value:
            return None
        try:
            parsed = parse_date(
                value, date_format(context) + ' ' + time_format(field))
        except (TypeError, ValueError, OverflowError):
            return None
        return to_server_datetime(parsed, context)
    if type_ == 'date':
        if not value:
            return None
        try:
            return parse_date(value, date_format(context)).date()
        except (TypeError, ValueError, OverflowError):
            return None
    if type_ == 'time':
        if not value:
            return None
        try:
            return parse_date(value, time_format(field)).time()
        except (TypeError, ValueError, OverflowError):
            return None
    if type_ == 'timedelta':
        return parse_timedelta(value, field, context)
    if type_ == 'many2one' and value == '':
        return None
    return value


def format_timedelta(value, field, context):
    seconds = value.total_seconds()
    sign = '-' if seconds < 0 else ''
    seconds = abs(seconds)
    converter = timedelta_converter(field, context)
    parts = []
    for unit in ('Y', 'M', 'w', 'd'):
        factor = converter.get(unit)
        if factor:
            amount = int(seconds // factor)
            seconds -= amount * factor
            if amount:
                parts.append('%d%s' % (amount, unit))
    hours = int(seconds // converter['h'])
    seconds -= hours * converter['h']
    minutes = int(seconds // converter['m'])
    seconds -= minutes * converter['m']
    if hours or minutes or seconds or not parts:
        clock = '%02d:%02d' % (hours, minutes)
        if seconds:
            clock += ':%02d' % int(seconds)
        parts.append(clock)
    return sign + ' '.join(parts)


def format_value(field, value, context, target=None, quote_empty=False):
    type_ = field.get('type')
    if isinstance(value, (list, tuple)):
        return ';'.join(format_value(
                field, item, context, quote_empty=True)
            for item in value)
    if type_ == 'boolean':
        result = _('False') if value is False else (
            _('True') if value else '')
    elif type_ in {'selection', 'multiselection'}:
        result = dict(valid_selection(field)).get(value, value) or ''
    elif type_ == 'reference':
        selections = dict(valid_selection(field))
        result = (
            '%s,%s' % (selections.get(target, target), value or '')
            if target else selections.get(value, value) or '')
    elif type_ in {'datetime', 'timestamp'}:
        if not value:
            result = ''
        else:
            value = to_local_datetime(value, context)
            format_ = date_format(context)
            if value.time() != datetime.time.min:
                format_ += ' ' + time_format(field)
            result = value.strftime(format_)
    elif type_ == 'date':
        result = value.strftime(date_format(context)) if value else ''
    elif type_ == 'time':
        result = value.strftime(time_format(field)) if value else ''
    elif type_ == 'timedelta':
        result = format_timedelta(value, field, context) if value else ''
    elif type_ == 'integer':
        if (isinstance(value, bool)
                or not isinstance(value, (int, float, Decimal))):
            result = ''
        else:
            factor = Decimal(str(field.get('factor', 1) or 1))
            result = str(int(Decimal(str(value)) * factor))
    elif type_ in {'float', 'numeric'}:
        if (isinstance(value, bool)
                or not isinstance(value, (int, float, Decimal))):
            result = ''
        else:
            factor = Decimal(str(field.get('factor', 1) or 1))
            result = str(Decimal(str(value)) * factor)
    elif value is None:
        result = ''
    else:
        result = str(value)
    return quote(str(result), empty=quote_empty)


class DomainParser:
    """Server-side port of Sao.common.DomainParser."""

    def __init__(self, fields, context=None):
        self.fields = OrderedDict()
        self.strings = OrderedDict()
        self.context = context or {}

        def update_fields(definitions, prefix='', string_prefix=''):
            for name, original in definitions.items():
                if not original or not original.get('searchable', True):
                    continue
                field = dict(original)
                full_name = '.'.join(filter(None, (prefix, name)))
                title = field.get('string') or name
                full_title = '.'.join(filter(None, (string_prefix, title)))
                field.update(name=full_name, string=full_title)
                self.fields[full_name] = field
                self.strings[full_title.casefold()] = field
                if field.get('relation_fields'):
                    update_fields(
                        field['relation_fields'], full_name, full_title)

        update_fields(fields)

    def parse(self, value):
        try:
            tokens = group_operator(iter(SearchLexer(value)))
            tokens = parenthesize(tokens)
            tokens = self.group(tokens)
            tokens = operatorize(tokens, 'or')
            tokens = operatorize(tokens, 'and')
            return simplify(recursive_list(self.parse_clause(tokens)))
        except ValueError as exception:
            if str(exception) == 'No closing quotation':
                return self.parse(value + '"')
            raise

    def group(self, tokens):
        def group_parts(parts):
            try:
                colon = parts.index(':')
            except ValueError:
                for part in parts:
                    yield (part,)
                return
            for start in range(colon):
                title = ' '.join(parts[start:colon])
                if title.casefold() not in self.strings:
                    continue
                if parts[:start]:
                    for part in parts[:start]:
                        yield (part,)
                else:
                    yield (None,)
                clause = (title,)
                if (colon + 1 < len(parts)
                        and parts[colon + 1] in ('',) + OPERATORS):
                    clause += (parts[colon + 1],)
                    colon += 1
                else:
                    clause += (None,)
                values = []
                while colon + 2 < len(parts) and parts[colon + 2] == ';':
                    values.append(parts[colon + 1])
                    colon += 2
                for grouped in group_parts(parts[colon + 1:]):
                    if clause:
                        if values:
                            if grouped[0] is not None:
                                values.append(grouped[0])
                            yield clause + (values,)
                        else:
                            yield clause + grouped
                        clause = None
                    else:
                        yield grouped
                if clause:
                    yield clause + ((values,) if values else (None,))
                break

        parts = []
        for token in tokens:
            if is_generator(token):
                for grouped in group_parts(parts):
                    if grouped != (None,):
                        yield grouped
                parts = []
                yield self.group(token)
            else:
                parts.append(token)
        for grouped in group_parts(parts):
            if grouped != (None,):
                yield grouped

    def parse_clause(self, tokens):
        for clause in tokens:
            if is_generator(clause):
                yield self.parse_clause(clause)
                continue
            if clause in ('OR', 'AND'):
                yield clause
                continue
            if len(clause) == 1:
                yield ('rec_name', 'ilike', likify(clause[0]))
                continue
            title, operator, value = clause
            field = self.strings[title.casefold()]
            field_name = field['name']
            target = None
            if field.get('type') == 'reference':
                if isinstance(value, str):
                    for key, label in valid_selection(field):
                        prefix = str(label) + ','
                        if value.casefold().startswith(prefix.casefold()):
                            target = key
                            value = value[len(prefix):]
                            field_name += '.rec_name'
                            break
            elif (field.get('type') == 'multiselection'
                    and value is not None and not isinstance(value, list)):
                value = [value]
            if not operator:
                operator = default_operator(field)
            if isinstance(value, list) and field.get('type') != 'multiselection':
                operator = 'not in' if operator == '!' else 'in'
            if operator == '!':
                operator = negate_operator(default_operator(field))
            if value is None and operator.endswith('in'):
                operator = '!=' if operator.startswith('not') else '='
            if field.get('type') in {
                    'integer', 'float', 'numeric', 'datetime', 'timestamp',
                    'date', 'time'}:
                if isinstance(value, str) and '..' in value:
                    left, right = value.split('..', 1)
                    yield iter([
                        (field_name, '>=', convert_value(
                                field, left, self.context)),
                        (field_name, '<=', convert_value(
                                field, right, self.context)),
                        ])
                    continue
                if (isinstance(value, str)
                        and field.get('type') in {'datetime', 'timestamp'}
                        and operator == '='):
                    try:
                        day = datetime.datetime.strptime(
                            value, date_format(self.context)).date()
                    except (TypeError, ValueError):
                        day = None
                    if day:
                        start = to_server_datetime(datetime.datetime.combine(
                                day, datetime.time()), self.context)
                        yield iter([
                            (field_name, '>=', start),
                            (field_name, '<', start + datetime.timedelta(days=1)),
                            ])
                        continue
            if field.get('type') in {
                    'many2one', 'one2many', 'many2many', 'one2one'} and value:
                field_name += '.rec_name'
            if isinstance(value, list):
                value = [
                    convert_value(field, item, self.context)
                    for item in value]
            else:
                value = convert_value(field, value, self.context)
            if 'like' in operator:
                value = likify(value)
            leaf = (field_name, operator, value)
            yield leaf + ((target,) if target else ())

    def string(self, domain):
        def stringify_clause(clause):
            if not clause:
                return ''
            if not isinstance(clause[0], str) or clause[0] in {'AND', 'OR'}:
                return '(%s)' % self.string(clause)
            name, operator, value = clause[:3]
            if name.endswith('.rec_name') and (value or len(clause) > 3):
                name = name[:-9]
            if name not in self.fields:
                if is_full_text(value):
                    value = value[1:-1]
                return quote(value)
            field = self.fields[name]
            target = clause[3] if len(clause) > 3 else None
            if 'ilike' in operator:
                if is_full_text(value):
                    value = value[1:-1]
                elif not is_like(value):
                    operator = '=' if operator == 'ilike' else '!'
                    value = unescape(value)
            default = default_operator(field)
            if default == operator.strip():
                operator = ''
                if value in OPERATORS:
                    operator = '"" '
            elif default in operator and ('not' in operator or '!' in operator):
                operator = operator.replace(default, '').replace(
                    'not', '!').strip()
            if operator.endswith('in'):
                if isinstance(value, (list, tuple)) and len(value) == 1:
                    operator = '!=' if operator == 'not in' else '='
                else:
                    operator = '!' if operator == 'not in' else ''
            formatted = format_value(field, value, self.context, target)
            if (operator in OPERATORS
                    and field.get('type') in {'char', 'text', 'selection'}
                    and value == ''):
                formatted = '""'
            return '%s: %s%s' % (
                quote(field['string']), operator, formatted)

        if not domain:
            return ''
        separator = ' '
        if domain[0] in ('AND', 'OR'):
            separator = ' | ' if domain[0] == 'OR' else ' '
            domain = domain[1:]
        return separator.join(stringify_clause(clause) for clause in domain)

    def completion(self, value):
        domain = self.parse(value)
        closing = 0
        for character in reversed(value):
            if character not in {')', ' '}:
                break
            if character == ')':
                closing += 1
        ending, depth = self.ending_clause(domain)
        depth -= closing

        def trim_depth(text):
            return text[:-depth] if depth > 0 else text

        canonical = trim_depth(self.string(domain))
        if canonical != value:
            yield canonical
        if ending is not None and closing == 0:
            for completed in self.complete(ending):
                yield trim_depth(self.string(recursive_list(
                    self.replace_ending_clause(domain, completed))))
        if value:
            if value[-1] != ' ':
                return
            if len(value) >= 2 and value[-2] == ':':
                return
        for field in self.strings.values():
            operator = default_operator(field)
            field_value = '%' if 'ilike' in operator else ''
            yield trim_depth(self.string(recursive_list(
                self.append_ending_clause(
                    domain, (field['name'], operator, field_value), depth))))

    def complete(self, clause):
        if len(clause) == 1:
            name, = clause
            operator = value = None
        elif len(clause) == 3:
            name, operator, value = clause
        else:
            name, operator, value, target = clause
            if name.endswith('.rec_name') and value:
                name = name[:-9]
            value = target
        if name == 'rec_name' and operator == 'ilike':
            escaped = value.replace('%%', '__')
            if escaped.startswith('%') and escaped.endswith('%'):
                value = value[1:-1]
            elif '%' not in escaped:
                value = value.replace('%%', '%')
            operator = None
            name, value = value, ''
        name = name or ''
        if name.casefold() not in self.strings and name not in self.fields:
            for field in self.strings.values():
                if field['string'].casefold().startswith(name.casefold()):
                    operator = default_operator(field)
                    field_value = '%' if 'ilike' in operator else ''
                    yield field['name'], operator, field_value
            return
        field = self.fields.get(name) or self.strings[name.casefold()]
        if not operator:
            operator = default_operator(field)
            field_value = '%' if 'ilike' in operator else ''
            yield field['name'], operator, field_value
            return
        for completed in self.complete_value(field, value):
            yield field['name'], operator, completed

    def complete_value(self, field, value):
        type_ = field.get('type')
        if type_ == 'boolean':
            if value is None:
                yield True
                yield False
            elif value:
                yield False
            else:
                yield True
        elif type_ in {'selection', 'multiselection', 'reference'}:
            test = value[-1] if isinstance(value, list) else value
            test = str(test or '').strip('%').casefold()
            for key, title in valid_selection(field):
                if str(title).casefold().startswith(test):
                    if isinstance(value, list):
                        yield value[:-1] + [key]
                    elif type_ == 'reference':
                        yield likify(str(key))
                    else:
                        yield key
        elif type_ in {'datetime', 'timestamp'}:
            yield datetime.date.today()
            yield datetime.datetime.now().replace(microsecond=0)
        elif type_ == 'date':
            yield datetime.date.today()
        elif type_ == 'time':
            yield datetime.datetime.now().time().replace(microsecond=0)

    def ending_clause(self, domain, depth=0):
        if not domain:
            return None, depth
        if isinstance(domain[-1], list):
            return self.ending_clause(domain[-1], depth + 1)
        return domain[-1], depth

    def replace_ending_clause(self, domain, clause):
        for item in domain[:-1]:
            yield item
        if isinstance(domain[-1], list):
            yield self.replace_ending_clause(domain[-1], clause)
        else:
            yield clause

    def append_ending_clause(self, domain, clause, depth):
        if not domain:
            yield clause
            return
        for item in domain[:-1]:
            yield item
        if isinstance(domain[-1], list):
            yield self.append_ending_clause(domain[-1], clause, depth - 1)
        else:
            yield domain[-1]
            if depth == 0:
                yield clause


def search_field_definitions(view):
    definitions = {
        name: dict(definition)
        for name, definition in view.get('fields', {}).items()
        }
    for name, title, type_ in COMMON_SEARCH_FIELDS:
        if name not in definitions:
            definitions[name] = {
                'name': name,
                'string': common_search_title(title),
                'type': type_,
                }
            if type_ == 'datetime':
                definitions[name]['format'] = '"%H:%M:%S"'
    return definitions


def parser_field_definitions(view):
    fields = view.get('fields', {})
    try:
        root = ElementTree.fromstring(view.get('arch') or '<tree/>')
    except ElementTree.ParseError:
        root = ElementTree.fromstring('<tree/>')
    definitions = OrderedDict()
    for node in root:
        if node.tag != 'field':
            continue
        name = node.attrib.get('name')
        if not name or name in definitions or name not in fields:
            continue
        definition = dict(fields[name])
        for attribute in ('string', 'factor'):
            if node.attrib.get(attribute):
                definition[attribute] = node.attrib[attribute]
        definitions[name] = definition
        symbol = node.attrib.get('symbol')
        if symbol and symbol not in definitions and symbol in fields:
            definitions[symbol] = dict(fields[symbol])
    if not definitions:
        definitions.update(
            (name, dict(definition))
            for name, definition in fields.items())
    for name, title, type_ in COMMON_SEARCH_FIELDS:
        if name not in definitions:
            definitions[name] = {
                'name': name,
                'string': common_search_title(title),
                'type': type_,
                }
            if type_ == 'datetime':
                definitions[name]['format'] = '"%H:%M:%S"'
    return definitions


def search_domain_parser(tab, view=None):
    Model = Pool().get(tab['model'])
    stored_context = decode_value(tab.get('search_context', {}))
    if stored_context:
        context = dict(stored_context)
    else:
        context = dict(
            Pool().get('res.user').get_preferences(context_only=True))
    context.update(Transaction().context)
    context.update(decode_value(tab.get('context', {})))
    context['locale'] = context.get('locale') or {}
    context.setdefault(
        'date_format', context['locale'].get('date') or '%Y-%m-%d')
    view = view or decode_value(tab.get('view', {}))
    try:
        root = ElementTree.fromstring(view.get('arch') or '<tree/>')
    except ElementTree.ParseError:
        root = None
    if root is None or root.tag != 'tree':
        view_types = tab.get('view_types', [])
        view_ids = tab.get('view_ids', [])
        view_id = None
        if 'tree' in view_types:
            index = view_types.index('tree')
            if index < len(view_ids):
                view_id = view_ids[index]
        with Transaction().set_context(context):
            view = Model.fields_view_get(
                view_id=view_id, view_type='tree')
    definitions = parser_field_definitions(view)
    for definition in definitions.values():
        selection = definition.get('selection')
        if not isinstance(selection, str):
            continue
        method = getattr(Model, selection, None)
        if not method:
            definition['selection'] = []
            continue
        try:
            change_with = definition.get('selection_change_with') or []
            definition['selection'] = (
                method({name: None for name in change_with})
                if change_with else method())
        except Exception:
            definition['selection'] = []
    return DomainParser(definitions, context)

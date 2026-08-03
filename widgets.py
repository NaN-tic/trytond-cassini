import base64
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from xml.etree import ElementTree

from dominate.tags import (
    a, button, div, img, input_, label, option, progress, select, span,
    textarea, ul)
from trytond.modules.xgettext import _
from trytond.pool import Pool
from trytond.pyson import PYSONDecoder
from trytond.tools import timezone
from trytond.tools.domain_inversion import domain_inversion, unique_value
from trytond.transaction import Transaction

from .icons import icon
from .search import date_format, to_local_datetime
from .state import decode_value


def dom_id(*parts):
    return '-'.join(
        str(part).replace('.', '-').replace('_', '-').replace('/', '-')
        for part in parts)


def stringify(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, datetime):
        zone = Transaction().context.get('timezone')
        if zone and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.UTC).astimezone(
                timezone.get_tzinfo(zone)).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value.total_seconds())
    if isinstance(value, (list, tuple, set)):
        return ','.join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


class HierarchyWidget:
    """Shared hierarchy presentation for menus and tree views with children."""

    @staticmethod
    def row(
            content, toggle=None, depth=0, expanded=False, extra_class=''):
        classes = ['vs-hierarchy-row']
        if depth:
            classes.append('vs-hierarchy-child')
        if expanded:
            classes.append('vs-hierarchy-expanded')
        if extra_class:
            classes.append(extra_class)
        with div(
                cls=' '.join(classes),
                style='--vs-hierarchy-depth:%d' % max(0, depth)) as row:
            if toggle is not None:
                row.add(toggle)
            else:
                span(
                    '', cls='vs-hierarchy-toggle-placeholder',
                    aria_hidden='true')
            with div(cls='vs-hierarchy-content') as body:
                body.add(content)
        return row

    @staticmethod
    def children(items):
        with ul(cls='vs-hierarchy-children') as children:
            for item in items:
                children.add(item)
        return children


class WidgetRenderer:
    """Dominate renderer for every field/widget family supported by Sao."""

    text_widgets = {
        'char', 'password', 'color', 'url', 'email', 'callto', 'sip',
        'pyson',
        }
    textarea_widgets = {'code', 'text', 'richtext', 'html'}
    numeric_widgets = {'integer', 'float', 'numeric', 'timedelta'}
    date_widgets = {'date', 'datetime', 'timestamp', 'time'}
    relation_widgets = {'many2one', 'one2one'}
    x2many_widgets = {'one2many', 'many2many'}
    binary_widgets = {'binary', 'image', 'document'}

    def __init__(self, tab, record, view, editable=True, endpoint='record'):
        self.tab = tab
        self.record = record
        self.view = view
        self.editable = editable
        self.endpoint = endpoint
        self.pool = Pool()
        self.Model = self.pool.get(tab['model'])
        self.values = decode_value(record.get('values', {}))
        self.root = ElementTree.fromstring(
            self.view.get('arch') or '<form/>')
        self.state_context = {}
        for name, value in self.values.items():
            field = self.Model._fields.get(name)
            if field and field._type in {'many2one', 'one2one'}:
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else None
            elif field and field._type in {'one2many', 'many2many'}:
                value = [
                    item.get('id') if isinstance(item, dict) else item
                    for item in (value or [])
                    ]
            self.state_context[name] = value
        for name in self.view.get('fields', {}):
            if name in self.state_context or name not in self.Model._fields:
                continue
            field = self.Model._fields[name]
            if field._type in {
                    'many2many', 'multiselection', 'one2many'}:
                self.state_context[name] = []
            elif field._type == 'boolean':
                self.state_context[name] = False
            else:
                self.state_context[name] = None
        record_id = self.record.get('id')
        if record_id is None and self.record.get('new'):
            record_id = -1
        self.state_context['id'] = record_id
        transaction_context = dict(Transaction().context)
        self.state_context['context'] = transaction_context
        self.state_context.update(transaction_context)

    def render(self, name, attributes=None, compact=False):
        attributes = dict(attributes or {})
        definition = self.view.get('fields', {}).get(name, {})
        widget = attributes.get('widget') or definition.get('type', 'char')
        value = self.values.get(name)
        readonly, required, invisible = self.states(definition, attributes)
        readonly = readonly or not self.editable
        field_id = dom_id(
            'field', self.tab['id'],
            self.record.get('dom_key', self.record['key']), name)
        style = attributes.get('_layout_style')
        if not compact:
            rules = []
            try:
                columns = max(1, int(attributes.get(
                        '_columns', self.root.attrib.get('col', 4))))
                colspan = max(1, int(attributes.get('colspan', 1)))
                rules.append(
                    'grid-column: span %d' % min(columns, colspan))
            except (TypeError, ValueError):
                pass
            try:
                rowspan = max(1, int(attributes.get('rowspan', 1)))
                if rowspan > 1:
                    rules.append('grid-row: span %d' % rowspan)
            except (TypeError, ValueError):
                pass
            if str(attributes.get('width', '')).isdigit():
                rules.append('min-width: %spx' % attributes['width'])
            if str(attributes.get('height', '')).isdigit():
                rules.append('min-height: %spx' % attributes['height'])
            if str(attributes.get('xfill', '1')).lower() in {
                    '0', 'false', 'no'}:
                try:
                    xalign = float(attributes.get('xalign', 0))
                except (TypeError, ValueError):
                    xalign = 0
                rules.append(
                    'justify-self: %s' % (
                        'end' if xalign >= .75
                        else 'center' if xalign >= .25
                        else 'start'))
            if str(attributes.get('yfill', '1')).lower() in {
                    '0', 'false', 'no'}:
                try:
                    yalign = float(attributes.get('yalign', .5))
                except (TypeError, ValueError):
                    yalign = .5
                rules.append(
                    'align-self: %s' % (
                        'end' if yalign >= .75
                        else 'center' if yalign >= .25
                        else 'start'))
            if style is None:
                style = ';'.join(rules) or None
        help_text = attributes.get('help')
        help_field = attributes.get('help_field')
        if help_field:
            help_text = self.values.get(help_field) or help_text

        with div(
                id=field_id,
                cls='vs-field%s%s' % (
                    ' vs-field-compact' if compact else '',
                    ' vs-hidden' if invisible else ''),
                data_field=name,
                data_widget=widget,
                data_accesskey=attributes.get('_accesskey'),
                title=help_text,
                style=style) as wrapper:
            control = self.control(
                name, widget, value, definition, attributes,
                field_id, readonly, required)
            symbol, position = self.get_symbol(
                value, definition, attributes)
            if symbol:
                with div(cls='vs-monetary-widget') as monetary:
                    if position < .5:
                        span(symbol, cls='vs-field-symbol vs-symbol-start')
                    monetary.add(control)
                    if position >= .5:
                        span(symbol, cls='vs-field-symbol vs-symbol-end')
            else:
                wrapper.add(control)
        return wrapper

    def get_symbol(self, value, definition, attributes):
        """Return the symbol and position defined for a numeric field."""
        symbol_name = attributes.get('symbol') or definition.get('symbol')
        if not symbol_name:
            return '', 1
        symbol_field = self.Model._fields.get(symbol_name)
        if not symbol_field:
            return stringify(symbol_name), 1
        symbol_value = self.values.get(symbol_name)
        if symbol_field._type not in {'many2one', 'one2one'}:
            return stringify(symbol_value), 1
        if isinstance(symbol_value, (list, tuple)):
            symbol_value = symbol_value[0] if symbol_value else None
        try:
            symbol_id = int(symbol_value)
        except (TypeError, ValueError):
            return '', 1
        if symbol_id <= 0:
            return '', 1
        try:
            if value is None or value == 0:
                sign = 0
            elif value < 0:
                sign = -1
            else:
                sign = 1
            symbol, position = self.pool.get(
                symbol_field.model_name)(symbol_id).get_symbol(sign)
            return stringify(symbol), float(position)
        except Exception:
            return '', 1

    def states(self, definition, attributes):
        readonly = bool(definition.get('readonly'))
        required = bool(definition.get('required'))
        invisible = False
        context = self.state_context
        state_values = (
            definition.get('states')
            if definition.get('states') is not None
            else attributes.get('states'))
        if isinstance(state_values, str):
            try:
                state_values = PYSONDecoder(context).decode(state_values)
            except Exception:
                state_values = {}
        if isinstance(state_values, dict):
            readonly = bool(state_values.get('readonly', readonly))
            required = bool(state_values.get('required', required))
            invisible = bool(state_values.get('invisible', invisible))
        for name, current in (
                ('readonly', readonly),
                ('required', required),
                ('invisible', invisible)):
            raw_value = attributes.get(name)
            if raw_value is not None:
                value = str(raw_value).lower() in {'1', 'true', 'yes'}
                if name == 'readonly':
                    readonly = value
                elif name == 'required':
                    required = value
                else:
                    invisible = value
        return readonly, required, invisible

    def evaluate(self, value, default=None):
        if value in (None, ''):
            return default
        if not isinstance(value, str):
            return value
        try:
            return PYSONDecoder(self.state_context).decode(value)
        except Exception:
            return default

    def htmx(self, name, field_id, widget):
        preserve_self = widget in (
            self.text_widgets | self.textarea_widgets
            | self.numeric_widgets | self.date_widgets)
        if self.endpoint == 'preferences':
            UpdateField = self.pool.get(
                'cassini.update.preference.field')
            trigger = 'change'
            synchronization = 'body:queue all'
            if widget in (
                    self.text_widgets | self.textarea_widgets
                    | self.numeric_widgets):
                trigger = 'input changed delay:400ms, change changed'
            return {
                'hx_post': UpdateField.url(field=name),
                'hx_trigger': trigger,
                'hx_target': '#' + field_id,
                'hx_swap': (
                    'none'
                    if preserve_self
                    else 'outerHTML'),
                'hx_include': 'this',
                'hx_sync': synchronization,
                }
        if self.endpoint == 'wizard':
            UpdateField = self.pool.get('cassini.update.wizard.field')
            trigger = 'change'
            synchronization = 'body:queue all'
            if widget in (
                    self.text_widgets | self.textarea_widgets
                    | self.numeric_widgets):
                trigger = 'input changed delay:400ms, change changed'
            return {
                'hx_post': UpdateField.url(
                    tab=self.tab['id'], field=name),
                'hx_trigger': trigger,
                'hx_target': '#' + field_id,
                'hx_swap': (
                    'none'
                    if preserve_self
                    else 'outerHTML'),
                'hx_include': 'this',
                'hx_sync': synchronization,
                }
        if self.endpoint == 'x2many':
            UpdateField = self.pool.get(
                'cassini.update.x2many.field')
            origin = self.tab['relation_origin']
            trigger = 'change'
            synchronization = 'body:queue all'
            if widget in (
                    self.text_widgets | self.textarea_widgets
                    | self.numeric_widgets):
                trigger = 'input changed delay:400ms, change changed'
            return {
                'hx_post': UpdateField.url(
                    tab=self.tab['id'], record=origin['record'],
                    field=origin['field'], item=self.record['key'],
                    child=name),
                'hx_trigger': trigger,
                'hx_target': '#' + field_id,
                'hx_swap': 'none' if preserve_self else 'outerHTML',
                'hx_include': 'this',
                'hx_sync': synchronization,
                }
        if self.endpoint != 'record':
            return {}
        UpdateField = self.pool.get('cassini.update.field')
        trigger = 'change'
        synchronization = 'body:queue all'
        if widget in (
                self.text_widgets | self.textarea_widgets
                | self.numeric_widgets):
            trigger = 'input changed delay:400ms, change changed'
        values = {
            'hx_post': UpdateField.url(
                tab=self.tab['id'], record=self.record['key'], field=name),
            'hx_trigger': trigger,
            'hx_target': '#' + field_id,
            'hx_swap': (
                'none'
                if preserve_self
                else 'outerHTML'),
            'hx_include': 'this',
            'hx_sync': synchronization,
            }
        return values

    @staticmethod
    def binary_size(value):
        """Return the byte size represented by a binary field value."""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def humanize_binary_size(cls, value):
        """Format a byte size with the same SI units as Sao."""
        size = cls.binary_size(value)
        units = ['', 'k', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y', 'R', 'Q']
        unit = ''
        for unit in units:
            if size <= 1000:
                break
            size /= 1000
        return '%s%sB' % (
            format(size, '.2f').rstrip('0').rstrip('.'), unit) if size else ''

    def binary_href(self, name, value):
        if not self.binary_size(value):
            return None
        if self.endpoint == 'record':
            Download = self.pool.get('cassini.download.binary')
            return Download.url(
                tab=self.tab['id'], record=self.record['key'], field=name)
        if self.endpoint == 'preferences':
            PreferenceBinary = self.pool.get('cassini.preference.binary')
            return PreferenceBinary.url(field=name)
        if self.endpoint == 'x2many':
            Download = self.pool.get('cassini.download.x2many.binary')
            origin = self.tab['relation_origin']
            return Download.url(
                tab=self.tab['id'], record=origin['record'],
                field=origin['field'], item=self.record['key'], child=name)
        return None

    def common_attributes(
            self, name, field_id, widget, readonly, required):
        values = {
            'id': field_id + '-input',
            'name': (
                'value'
                if self.endpoint in {'record', 'x2many'} else name),
            'disabled': readonly or None,
            'required': required or None,
            'aria_required': str(bool(required)).lower(),
            'cls': 'vs-input',
            'hx_preserve': 'true',
            }
        values.update(self.htmx(name, field_id, widget))
        return values

    def temporal_control(
            self, widget, value, definition, common, readonly):
        context = dict(
            self.pool.get('res.user').get_preferences(context_only=True))
        context.update(Transaction().context)
        context.update(decode_value(self.tab.get('context', {})))
        date_format_ = date_format(context)
        time_format_ = self.evaluate(
            definition.get('format'), '%H:%M:%S') or '%H:%M:%S'
        if widget == 'date':
            format_ = date_format_
            input_type = 'date'
        elif widget == 'time':
            format_ = time_format_
            input_type = 'time'
        else:
            format_ = '%s %s' % (date_format_, time_format_)
            input_type = 'datetime-local'

        local_value = value
        if isinstance(value, datetime):
            local_value = to_local_datetime(value, context)
        display_value = (
            local_value.strftime(format_) if local_value else '')
        if isinstance(local_value, datetime):
            picker_value = local_value.isoformat(timespec='seconds')
        elif isinstance(local_value, time):
            picker_value = local_value.isoformat(timespec='seconds')
        elif isinstance(local_value, date):
            picker_value = local_value.isoformat()
        else:
            picker_value = ''

        common['data_temporal_input'] = 'true'
        common['data_temporal_kind'] = widget
        common['data_temporal_value'] = picker_value
        common['data_temporal_format'] = format_
        common['cls'] += ' vs-temporal-entry'
        with div(
                cls='vs-temporal-widget',
                data_temporal_widget='true') as control:
            input_(type='text', value=display_value,
                autocomplete='off', **common)
            if not readonly:
                with span(cls='vs-temporal-picker'):
                    with button(
                            type='button', tabindex='-1',
                            cls='vs-temporal-picker-button',
                            title=definition.get('string') or ''):
                        icon('date')
                    input_(
                        type=input_type, value=picker_value,
                        tabindex='-1', aria_hidden='true',
                        cls='vs-temporal-picker-input',
                        data_temporal_picker_input='true')
        return control

    def control(
            self, name, widget, value, definition, attributes,
            field_id, readonly, required):
        common = self.common_attributes(
            name, field_id, widget, readonly, required)
        common['placeholder'] = attributes.get('help')
        common['accesskey'] = attributes.get('_accesskey')
        common['autofocus'] = (
            str(attributes.get('autofocus', '')).lower()
            in {'1', 'true', 'yes'} or None)
        if attributes.get('spell') is not None:
            common['spellcheck'] = str(attributes.get('spell')).lower() in {
                '1', 'true', 'yes'}

        if widget in self.text_widgets:
            input_type = {
                'password': 'password',
                'color': 'color',
                'email': 'email',
                'url': 'url',
                'callto': 'tel',
                'sip': 'text',
                }.get(widget, 'text')
            if definition.get('size'):
                common['maxlength'] = definition['size']
            return input_(
                type=input_type, value=stringify(value),
                autocomplete='off', **common)

        if widget == 'code' and 'widgets' in self.pool._modules:
            try:
                height = max(200, int(attributes.get('height') or 400))
            except (TypeError, ValueError):
                height = 400
            language = (
                attributes.get('language')
                or attributes.get('mode')
                or 'plaintext')
            if '/' in language:
                language = language.rsplit('/', 1)[-1]
            language = language.removeprefix('x-')
            if language.endswith('+json'):
                language = 'json'
            elif language.endswith('+xml'):
                language = 'xml'
            common['cls'] += ' vs-code-source'
            common['data_code_source'] = 'true'
            with div(
                    cls='vs-code-widget',
                    data_code_widget='true',
                    data_code_language=language,
                    data_code_readonly=str(bool(readonly)).lower(),
                    style='min-height:%dpx' % height) as control:
                textarea(stringify(value), rows=12, **common)
                div(
                    cls='vs-code-editor',
                    data_code_editor='true',
                    style='height:%dpx' % height)
            return control

        if widget in self.textarea_widgets:
            return textarea(
                stringify(value), rows=attributes.get('height', 5), **common)

        if widget == 'chart':
            try:
                height = max(120, int(attributes.get('height') or 450))
            except (TypeError, ValueError):
                height = 450
            payload = base64.b64encode(
                stringify(value).encode('utf-8')).decode('ascii')
            return div(
                cls='vs-chart',
                data_cassini_chart='true',
                data_chart_payload=payload,
                style='min-height:%dpx' % height,
                role='img',
                aria_label=(
                    attributes.get('string')
                    or definition.get('string')
                    or name))

        if widget in self.numeric_widgets:
            step = '1' if widget == 'integer' else 'any'
            factor = float(attributes.get('factor', 1) or 1)
            display_value = value
            if display_value not in (None, '') and factor != 1:
                display_value = (
                    display_value / Decimal(str(factor))
                    if isinstance(display_value, Decimal)
                    else display_value / factor)
            common['cls'] += ' vs-numeric-input'
            return input_(
                type='number', step=step,
                value=stringify(display_value), **common)

        if widget in self.date_widgets:
            return self.temporal_control(
                widget, value, definition, common, readonly)

        if widget == 'boolean':
            common.pop('required', None)
            return input_(
                type='checkbox', value='true', checked=bool(value) or None,
                **common)

        if widget in {'selection', 'multiselection'}:
            choices = self.selection(definition)
            multiple = widget == 'multiselection'
            selected = (
                {str(item) for item in (value or [])}
                if multiple else {value})
            with select(
                    multiple=multiple or None,
                    size=max(2, len(choices)) if multiple else None,
                    **common) as control:
                has_selected_choice = any(
                    key in selected for key, _label in choices)
                if (
                        not multiple
                        and (
                            not required
                            or not has_selected_choice)):
                    option('', value='', selected=value in (None, ''))
                for key, title in choices:
                    option(
                        title, value=stringify(key),
                        selected=(
                            str(key) in selected if multiple
                            else key in selected) or None)
            return control

        if widget in self.relation_widgets:
            relation_value = value
            if isinstance(relation_value, (list, tuple)):
                relation_value = (
                    relation_value[0] if relation_value else None)
            title = self.relation_title(definition, relation_value)
            suggestions_id = field_id + '-suggestions'
            RelationAutocomplete = self.pool.get(
                'cassini.relation.autocomplete')
            RelationSearch = self.pool.get(
                'cassini.relation.search')
            OpenRelationNew = self.pool.get(
                'cassini.open.relation.new')
            OpenRelationRecord = self.pool.get(
                'cassini.open.relation.record')
            OpenResource = self.pool.get(
                'cassini.open.resource')
            relation = definition.get('relation')
            relation_access = {
                'read': False, 'write': False,
                'create': False, 'delete': False}
            if relation:
                ModelAccess = self.pool.get('ir.model.access')
                relation_access.update(
                    ModelAccess.get_access([relation])[relation])
            modal_target = (
                '#relation-modal'
                if self.endpoint == 'preferences' else '#modal')
            hidden = dict(common)
            hidden['id'] = field_id + '-value'
            with div(
                    cls='vs-relation',
                    data_relation_widget='true') as control:
                with div(cls='vs-relation-input-group'):
                    input_(
                        id=field_id + '-input',
                        type='text',
                        name='query',
                        value=title or '',
                        autocomplete='off',
                        disabled=readonly or None,
                        required=required or None,
                        cls='vs-input vs-relation-entry',
                        data_relation_input='true',
                        data_relation_value=field_id + '-value',
                        data_relation_selected_title=title or '',
                        hx_post=(
                            RelationAutocomplete.url(
                                tab=self.tab['id'],
                                record=self.record['key'],
                                field=name)
                            if str(attributes.get(
                                    'completion', '1')).lower()
                            not in {'0', 'false', 'no'}
                            else None),
                        hx_trigger=(
                            'input changed delay:250ms'
                            if str(attributes.get(
                                    'completion', '1')).lower()
                            not in {'0', 'false', 'no'}
                            else None),
                        hx_target='#' + suggestions_id,
                        hx_swap='outerHTML',
                        hx_sync='this:replace',
                        hx_include='this')
                    if relation_value and relation_access['read']:
                        with button(
                                type='button',
                                cls=(
                                    'vs-relation-icon '
                                    'vs-relation-icon-primary'),
                                title=_('Open the record'),
                                aria_label=_('Open the record'),
                                tabindex='-1',
                                hx_post=OpenRelationRecord.url(
                                    tab=self.tab['id'],
                                    model=definition.get('relation'),
                                    record=relation_value,
                                    source_record=self.record['key'],
                                    field=name),
                                hx_target='#workspace',
                                hx_swap='outerHTML',
                                data_relation_open='true',
                                data_open_tab_url=OpenResource.url(
                                    model=definition.get('relation'),
                                    record=relation_value)):
                            icon('open')
                        if not readonly:
                            with button(
                                    type='button',
                                    cls=(
                                        'vs-relation-icon '
                                        'vs-relation-icon-secondary'),
                                    title=_('Clear the field'),
                                    aria_label=_('Clear the field'),
                                    tabindex='-1',
                                    data_relation_clear='true'):
                                icon('clear')
                    elif not readonly and relation_access['read']:
                        with button(
                                type='button',
                                cls=(
                                    'vs-relation-icon '
                                    'vs-relation-icon-secondary'),
                                title=_('Search a record'),
                                aria_label=_('Search a record'),
                                tabindex='-1',
                                hx_get=RelationSearch.url(
                                    tab=self.tab['id'],
                                    record=self.record['key'],
                                    field=name),
                                hx_include='#' + field_id + '-input',
                                hx_target=modal_target,
                                hx_swap='innerHTML'):
                            icon('search')
                input_(
                    type='hidden',
                    value=relation_value or '',
                    data_relation_hidden='true',
                    **hidden)
                control.add(self.relation_suggestions(
                        suggestions_id, [],
                        search_url=RelationSearch.url(
                            tab=self.tab['id'],
                            record=self.record['key'],
                            field=name),
                        new_url=(
                            OpenRelationNew.url(
                                tab=self.tab['id'],
                                record=self.record['key'],
                                field=name)
                            if (
                                not readonly
                                and relation_access['create']
                                and str(attributes.get(
                                        'create', '1')).lower()
                                not in {'0', 'false', 'no'})
                            else None),
                        modal_target=modal_target,
                        input_id=field_id + '-input'))
            return control

        if widget == 'reference':
            model, record_id = (str(value).split(',', 1) + [''])[:2] \
                if value else ('', '')
            title = ''
            if model and record_id.isdigit():
                try:
                    title = self.pool.get(model)(int(record_id)).rec_name
                except KeyError:
                    pass
            suggestions_id = field_id + '-suggestions'
            ReferenceAutocomplete = self.pool.get(
                'cassini.reference.autocomplete')
            with div(cls='vs-reference', data_reference_widget='true') as control:
                with select(
                        name='model', cls='vs-input vs-reference-model',
                        disabled=readonly or None,
                        aria_label=definition.get('string') or name,
                        data_reference_model='true'):
                    option('', value='', selected=not model or None)
                    for choice, label_ in self.selection(definition):
                        option(label_, value=choice,
                            selected=choice == model or None)
                input_(
                    type='text', name='query', value=title,
                    autocomplete='off', disabled=readonly or None,
                    cls='vs-input vs-reference-entry',
                    data_reference_input='true',
                    hx_post=ReferenceAutocomplete.url(
                        tab=self.tab['id'], record=self.record['key'],
                        field=name),
                    hx_trigger='input changed delay:250ms',
                    hx_target='#' + suggestions_id, hx_swap='outerHTML',
                    hx_sync='this:replace', hx_include='closest .vs-reference')
                hidden = dict(common)
                hidden['id'] = field_id + '-value'
                input_(type='hidden', value=stringify(value),
                    data_reference_hidden='true', **hidden)
                with div(id=suggestions_id, cls='vs-relation-completion',
                        role='listbox'):
                    pass
            return control

        if widget in self.x2many_widgets:
            return self.x2many(
                name, widget, value, definition, attributes,
                field_id, readonly, required)

        if widget in self.binary_widgets:
            binary_htmx = self.htmx(name, field_id, widget)
            binary_htmx['hx_encoding'] = 'multipart/form-data'
            filename_field = (
                attributes.get('filename')
                or definition.get('filename')
                or getattr(self.Model._fields.get(name), 'filename', None))
            filename = self.values.get(filename_field)
            size = self.binary_size(value)
            href = self.binary_href(name, value)
            binary_name = (
                'value'
                if self.endpoint in {'record', 'wizard', 'x2many'} else name)
            if widget == 'image':
                try:
                    width = max(24, int(attributes.get('width', 300)))
                except (TypeError, ValueError):
                    width = 300
                try:
                    height = max(24, int(attributes.get('height', 100)))
                except (TypeError, ValueError):
                    height = 100
                border = attributes.get('border', 'square')
                with div(cls='vs-binary vs-image-widget') as control:
                    with div(
                            cls='vs-image-frame',
                            style='width:%spx;height:%spx' % (
                                width, height)):
                        if value and href:
                            img(
                                src=href,
                                alt=definition.get('string', name),
                                cls='vs-image-preview vs-image-' + border)
                        else:
                            title = stringify(
                                self.values.get('name')
                                or definition.get('string')
                                or name)
                            span(
                                title[:1].upper(),
                                cls=(
                                    'vs-image-placeholder '
                                    'vs-image-' + border),
                                aria_hidden='true')
                    if not readonly or (value and href):
                        with div(
                                cls='vs-image-toolbar',
                                role='group',
                                aria_label=_('Image actions')):
                            if size and href:
                                with a(
                                        href=href,
                                        cls='vs-icon-button',
                                        title=_('Save as'),
                                        aria_label=_('Save as'),
                                        download=filename or None):
                                    icon('download')
                            elif not size and not readonly:
                                with label(
                                        cls=(
                                            'vs-icon-button '
                                            'vs-file-select'),
                                        title=_('Select'),
                                        aria_label=_('Select')):
                                    input_(
                                        id=field_id + '-input',
                                        name=binary_name,
                                        type='file',
                                        accept=(
                                            'image/png,image/jpeg,image/gif,'
                                            '.png,.jpg,.jpeg,.gif,.tif,.xpm'),
                                        cls='vs-file-input',
                                        **binary_htmx)
                                    icon('search')
                            if value and not readonly:
                                clear_values = self.htmx(
                                    name, field_id, widget)
                                clear_values['hx_trigger'] = 'click'
                                clear_values['hx_vals'] = json.dumps({
                                        binary_name: ''})
                                with button(
                                        type='button',
                                        cls='vs-icon-button',
                                        title=_('Clear'),
                                        aria_label=_('Clear'),
                                        **clear_values):
                                    icon('clear')
                return control
            filename_visible = (
                filename_field
                and str(attributes.get(
                    'filename_visible', '0')).lower()
                not in {'0', 'false', 'no'})
            with div(
                    cls='vs-binary-widget',
                    data_binary_filename_visible=(
                        'true' if filename_visible else None)) as control:
                with div(cls='vs-binary-input-group'):
                    if filename_visible:
                        filename_id = field_id + '-filename'
                        filename_attributes = self.common_attributes(
                            filename_field, filename_id, 'char',
                            readonly, False)
                        filename_attributes.update({
                                'id': filename_id + '-input',
                                'value': stringify(filename),
                                'cls': 'vs-input vs-binary-filename',
                                'data_binary_filename': 'true',
                                'hx_target': '#' + field_id,
                                'hx_swap': 'none',
                                'hx_trigger': 'change',
                                })
                        input_(type='text', **filename_attributes)
                    input_(
                        type='text', readonly=True,
                        value=self.humanize_binary_size(size),
                        cls='vs-input vs-binary-size',
                        aria_label=_('Size'), data_binary_size='true')
                    with div(
                            cls='vs-binary-actions', role='group',
                            aria_label=_('Binary actions')):
                        if href:
                            with a(
                                    href=href,
                                    cls='vs-icon-button',
                                    title=_('Save as'),
                                    aria_label=_('Save as'),
                                    download=filename or None):
                                icon('download')
                        if not size and not readonly:
                            with label(
                                    cls=(
                                        'vs-icon-button '
                                        'vs-file-select'),
                                    title=_('Select'),
                                    aria_label=_('Select'),
                                    data_binary_select='true'):
                                input_(
                                    id=field_id + '-input',
                                    name=binary_name,
                                    type='file', cls='vs-file-input',
                                    **binary_htmx)
                                icon('search')
                        if size and not readonly:
                            clear_values = self.htmx(name, field_id, widget)
                            clear_values['hx_trigger'] = 'click'
                            clear_values['hx_vals'] = json.dumps({
                                    binary_name: ''})
                            with button(
                                    type='button', cls='vs-icon-button',
                                    title=_('Clear'), aria_label=_('Clear'),
                                    **clear_values):
                                icon('clear')
            return control

        if widget == 'progressbar':
            numeric = float(value or 0)
            maximum = float(attributes.get('max', 1) or 1)
            with div(cls='vs-progress') as control:
                progress(value=numeric, max=maximum)
                span('%d%%' % (100 * numeric / maximum if maximum else 0))
            return control

        if widget == 'dict':
            return textarea(
                stringify(value), rows=attributes.get('height', 6), **common)

        return input_(type='text', value=stringify(value), **common)

    @staticmethod
    def x2many_item_key(item, index):
        if isinstance(item, dict) and item.get('__key__'):
            return str(item['__key__'])
        if isinstance(item, dict) and item.get('id'):
            return str(item['id'])
        if isinstance(item, int):
            return str(item)
        if str(item).lstrip('-').isdigit():
            return str(item)
        return 'new-%d' % index

    def x2many_view(self, definition, attributes, view_type):
        Relation = self.pool.get(definition['relation'])
        modes = [
            mode.strip() for mode in attributes.get(
                'mode', 'tree,form').split(',')
            if mode.strip()]
        view_ids = [
            view_id.strip() for view_id in attributes.get(
                'view_ids', '').split(',')]
        view_id = None
        if view_type in modes:
            index = modes.index(view_type)
            if index < len(view_ids):
                reference = view_ids[index]
                if reference.isdigit():
                    view_id = int(reference)
                elif '.' in reference:
                    module, fs_id = reference.split('.', 1)
                    try:
                        view_id = self.pool.get(
                            'ir.model.data').get_id(module, fs_id)
                    except KeyError:
                        view_id = None
        context = {}
        screen_width = self.tab.get('screen_width')
        if screen_width:
            context.update({
                    'screen_size': (int(screen_width), 0),
                    'view_tree_width': True,
                    })
        with Transaction().set_context(context):
            return Relation.fields_view_get(
                view_id=view_id, view_type=view_type)

    @staticmethod
    def tree_read_fields(view, Model):
        """Return every model field required by the shared tree renderer."""
        root = ElementTree.fromstring(view.get('arch') or '<tree/>')
        names = [
            name for name in view.get('fields', {})
            if name in Model._fields
            and Model._fields[name]._type != 'binary']
        for node in root.iter('field'):
            name = node.attrib.get('name')
            definition = view.get('fields', {}).get(name, {})
            if (
                    name in Model._fields
                    and Model._fields[name]._type == 'binary'
                    and name not in names):
                names.append(name)
            filename = (
                node.attrib.get('filename')
                or getattr(Model._fields.get(name), 'filename', None))
            if filename in Model._fields and filename not in names:
                names.append(filename)
            symbol = node.attrib.get('symbol') or definition.get('symbol')
            if symbol in Model._fields and symbol not in names:
                names.append(symbol)
            candidates = [node.attrib.get('name'), node.attrib.get('icon')]
            for affix in node:
                if affix.tag not in {'prefix', 'suffix'}:
                    continue
                candidates.extend([
                        affix.attrib.get('name', node.attrib.get('name')),
                        affix.attrib.get('icon'),
                        ])
            for name in candidates:
                if (
                        name in Model._fields
                        and Model._fields[name]._type != 'binary'
                        and name not in names):
                    names.append(name)
        child_field = view.get('field_childs')
        if (
                child_field in Model._fields
                and Model._fields[child_field]._type != 'binary'
                and child_field not in names):
            names.append(child_field)
        if 'rec_name' not in names:
            names.append('rec_name')
        return names

    def x2many_rows(self, definition, attributes, values, state, view_type):
        deleted = list(state.get('deleted', []))
        entries = []
        for index, item in enumerate(list(values or []) + deleted):
            entries.append({
                    'key': self.x2many_item_key(item, index),
                    'item': item,
                    'id': (
                        item.get('id') if isinstance(item, dict)
                        else int(item)
                        if str(item).lstrip('-').isdigit()
                        else None),
                    'deleted': index >= len(values or []),
                    })
        relation_view = self.x2many_view(
            definition, attributes, view_type)
        Relation = self.pool.get(definition['relation'])
        read_fields = self.tree_read_fields(relation_view, Relation)
        ids = [entry['id'] for entry in entries if entry['id']]
        binary_context = {
            '%s.%s' % (Relation.__name__, name): 'size'
            for name in read_fields
            if (name in Relation._fields
                and Relation._fields[name]._type == 'binary')
            }
        with Transaction().set_context(binary_context):
            records = {
                record['id']: record
                for record in Relation.read(ids, read_fields)
                } if ids else {}
        for entry in entries:
            item = entry['item']
            if entry['id']:
                entry['values'] = records.get(entry['id'], {})
                if isinstance(item, dict):
                    entry['values'].update(decode_value(
                            item.get('values', {})))
            elif isinstance(item, dict):
                entry['values'] = decode_value(
                    item.get('values', item))
                entry['values'].setdefault(
                    'rec_name',
                    entry['values'].get(
                        Relation._rec_name, _('New record')))
            else:
                entry['values'] = {'rec_name': stringify(item)}
        return relation_view, entries

    def tree_affix(self, attributes, protocol=None):
        attributes = dict(attributes)
        name = attributes.get('name')
        definition = self.view.get('fields', {}).get(name, {})
        if name and self.states(definition, attributes)[2]:
            return None
        value = self.values.get(name)
        icon_name = attributes.get('icon')
        if icon_name and icon_name in self.Model._fields:
            icon_name = self.values.get(icon_name)
        icon_type = attributes.get('icon_type', 'icon')
        title = attributes.get('string', '')
        border = attributes.get('border')
        image_class = 'vs-tree-affix'
        if border in {'rounded', 'circle'}:
            image_class += ' vs-image-' + border
        if protocol:
            href = stringify(value)
            if href:
                href = {
                    'email': 'mailto:',
                    'callto': 'callto:',
                    'sip': 'sip:',
                    }.get(protocol, '') + href
            with a(
                    href=href or None,
                    target='_blank', rel='noreferrer noopener',
                    cls=image_class,
                    title=title or stringify(value)) as link:
                icon(icon_name or 'public')
            return link
        if icon_name:
            if icon_type == 'url':
                return img(
                    src=icon_name, alt=title,
                    cls=image_class)
            if icon_type == 'color':
                from .views import css_color
                color = css_color(icon_name)
                return span(
                    '', cls=image_class + ' vs-tree-affix-color',
                    style=(
                        'background-color:%s' % color if color else None),
                    title=title)
            with span(cls=image_class, title=title) as image:
                icon(str(icon_name).removeprefix('tryton-'))
            return image
        text = title if title else stringify(value)
        if text:
            return span(text, cls=image_class)
        return None

    def x2many_suggestions(
            self, id_, choices, name, field_id, can_create=False,
            modal_target='#modal', input_id=None, open_=False):
        X2ManyAction = self.pool.get('cassini.x2many.action')
        RelationSearch = self.pool.get('cassini.relation.search')
        OpenRelationNew = self.pool.get('cassini.open.relation.new')
        include = '#' + input_id if input_id else None
        with div(
                id=id_, cls='vs-relation-completion',
                role='listbox',
                data_open=str(bool(open_)).lower()) as suggestions:
            for record_id, title in choices:
                button(
                    title, type='button',
                    cls='vs-relation-option',
                    role='option',
                    data_many2many_choice=record_id,
                    hx_post=X2ManyAction.url(
                        tab=self.tab['id'],
                        record=self.record['key'],
                        field=name,
                        action='add'),
                    hx_vals=json.dumps({'value': record_id}),
                    hx_target='#' + field_id,
                    hx_swap='outerHTML')
            with div(cls='vs-relation-completion-actions'):
                button(
                    _('Search…'), type='button',
                    cls='vs-relation-completion-action',
                    hx_get=RelationSearch.url(
                        tab=self.tab['id'],
                        record=self.record['key'],
                        field=name),
                    hx_include=include,
                    hx_target=modal_target,
                    hx_swap='innerHTML')
                if can_create and self.endpoint != 'preferences':
                    button(
                        _('Create…'), type='button',
                        cls='vs-relation-completion-action',
                        hx_post=OpenRelationNew.url(
                            tab=self.tab['id'],
                            record=self.record['key'],
                            field=name),
                        hx_include=include,
                        hx_target='#workspace',
                        hx_swap='outerHTML')
        return suggestions

    def x2many(
            self, name, widget, value, definition, attributes,
            field_id, readonly, required):
        X2ManyAction = self.pool.get('cassini.x2many.action')
        RelationAutocomplete = self.pool.get(
            'cassini.relation.autocomplete')
        OpenRelationNew = self.pool.get(
            'cassini.open.relation.new')
        RelationSearch = self.pool.get(
            'cassini.relation.search')
        OpenRelationRecord = self.pool.get(
            'cassini.open.relation.record')
        relation = definition.get('relation')
        if self.tab.get('_x2many_form_depth', 0) >= 1:
            with div(
                    id=field_id + '-input',
                    cls='vs-x2many-panel vs-x2many-nested-summary') as control:
                label(
                    attributes.get('string')
                    or definition.get('string')
                    or name,
                    cls='vs-x2many-string%s' % (
                        ' vs-label-required' if required else ''))
                span(
                    _('%(count)d record') % {
                        'count': len(value or [])}
                    if len(value or []) == 1 else
                    _('%(count)d records') % {
                        'count': len(value or [])},
                    cls='vs-x2many-nested-count')
            return control
        relation_access = {
            'read': False, 'write': False,
            'create': False, 'delete': False}
        if relation:
            ModelAccess = self.pool.get('ir.model.access')
            relation_access.update(
                ModelAccess.get_access([relation])[relation])
        modal_target = (
            '#relation-modal'
            if self.endpoint == 'preferences' else '#modal')
        modes = (
            ['tree']
            if widget == 'many2many' else [
                mode.strip() for mode in attributes.get(
                    'mode', 'tree,form').split(',')
                if mode.strip() in {'tree', 'form'}])
        if not modes:
            modes = ['tree']
        state = self.record.setdefault(
            'x2many', {}).setdefault(name, {
                'view': modes[0],
                'current': None,
                'deleted': [],
                })
        view_type = state.get('view')
        if view_type not in modes:
            view_type = modes[0]
            state['view'] = view_type
        relation_view, rows = self.x2many_rows(
            definition, attributes, value, state, view_type)
        relation_root = ElementTree.fromstring(
            relation_view.get('arch') or '<tree/>')
        inline_create = (
            widget == 'one2many'
            and view_type == 'tree'
            and relation_root.attrib.get('editable') in {
                '1', 'top', 'bottom'}
            and str(relation_root.attrib.get(
                    'creatable', '1')).lower()
            not in {'0', 'false', 'no'})
        row_keys = [row['key'] for row in rows]
        current = state.get('current')
        if current not in row_keys:
            current = row_keys[0] if row_keys else None
            state['current'] = current
        stored_selection = state.get('selected')
        selected = (
            [key for key in stored_selection if key in row_keys]
            if stored_selection is not None else
            [current] if current else [])
        state['selected'] = selected
        position = row_keys.index(current) + 1 if current else 0
        current_row = next(
            (row for row in rows if row['key'] == current), None)
        can_create = (
            not readonly
            and relation_access['create']
            and str(attributes.get('create', '1')).lower()
            not in {'0', 'false', 'no'})
        can_delete = (
            not readonly
            and (
                widget == 'many2many'
                or relation_access['delete'])
            and str(attributes.get('delete', '1')).lower()
            not in {'0', 'false', 'no'})
        size = self.evaluate(attributes.get('size'))
        size_limit = (
            widget == 'many2many'
            and isinstance(size, (int, float))
            and not isinstance(size, bool)
            and size >= 0
            and len(value or []) >= size)
        has_add_remove = (
            widget == 'many2many'
            or attributes.get(
                'add_remove', definition.get('add_remove')) is not None)
        can_add = (
            has_add_remove
            and not readonly
            and relation_access['read']
            and not size_limit)
        if widget == 'many2many' and size_limit:
            can_create = False
        target = '#' + field_id

        def action_button(
                action, image, title, disabled=False, values=None,
                include=None):
            with button(
                    type='button',
                    cls='vs-icon-button',
                    title=title,
                    aria_label=title,
                    disabled=disabled or None,
                    hx_post=(
                        X2ManyAction.url(
                            tab=self.tab['id'],
                            record=self.record['key'],
                            field=name,
                            action=action)
                        if not disabled else None),
                    hx_vals=json.dumps(values) if values else None,
                    hx_include=include,
                    hx_target=target,
                    hx_swap='outerHTML'):
                icon(image)

        with div(
                id=field_id + '-input',
                cls='vs-x2many-panel%s' % (
                    ' vs-many2many-panel'
                    if widget == 'many2many' else ' vs-one2many-panel'),
                data_x2many=name,
                data_orientation=attributes.get(
                    'orientation', 'left_to_right')) as control:
            with div(cls='vs-x2many-menu'):
                label(
                    attributes.get('string')
                    or definition.get('string')
                    or name,
                    cls='vs-x2many-string%s' % (
                        ' vs-label-required' if required else ''))
                with div(
                        cls='vs-x2many-toolbar',
                        role='toolbar',
                        aria_label=_('Relation actions')):
                    if has_add_remove:
                        suggestions_id = field_id + '-suggestions'
                        entry_id = field_id + '-relation-input'
                        with div(
                                cls=(
                                    'vs-relation '
                                    'vs-many2many-entry'),
                                data_x2many_add_widget='true',
                                data_many2many_widget=(
                                    'true'
                                    if widget == 'many2many' else None)) as entry:
                            input_(
                                id=entry_id,
                                type='text', name='query',
                                autocomplete='off',
                                disabled=not can_add or None,
                                cls='vs-input vs-x2many-add-input',
                                placeholder=attributes.get('help'),
                                data_x2many_add_input='true',
                                data_many2many_input=(
                                    'true'
                                    if widget == 'many2many' else None),
                                hx_post=(
                                    RelationAutocomplete.url(
                                        tab=self.tab['id'],
                                        record=self.record['key'],
                                        field=name)
                                    if can_add and str(attributes.get(
                                        'completion', '1')).lower()
                                    not in {'0', 'false', 'no'} else None),
                                hx_trigger=(
                                    'input changed delay:250ms'
                                    if can_add and str(attributes.get(
                                        'completion', '1')).lower()
                                    not in {'0', 'false', 'no'} else None),
                                hx_target='#' + suggestions_id,
                                hx_swap='outerHTML',
                                hx_sync='this:replace',
                                hx_include='this')
                            entry.add(self.x2many_suggestions(
                                    suggestions_id, [], name, field_id,
                                    can_create=can_create,
                                    modal_target=modal_target,
                                    input_id=entry_id))
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=_('Add'),
                                aria_label=_('Add'),
                                disabled=not can_add or None,
                                hx_get=(
                                    RelationSearch.url(
                                        tab=self.tab['id'],
                                        record=self.record['key'],
                                        field=name)
                                    if can_add else None),
                                hx_include=(
                                    '#' + entry_id if can_add else None),
                                hx_target=modal_target,
                                hx_swap='innerHTML',
                                data_x2many_add='true',
                                data_many2many_add=(
                                    'true'
                                    if widget == 'many2many' else None)):
                            icon('add')
                    if widget == 'many2many':
                        span(
                            '%s / %s' % (
                                position if position else '_', len(rows)),
                            cls='vs-x2many-badge',
                            title='%s / %s' % (
                                position if position else '_', len(rows)))
                        action_button(
                            'remove', 'remove', _('Remove'),
                            disabled=not can_delete or not current_row)
                        action_button(
                            'undelete', 'undo', _('Undelete'),
                            disabled=not can_delete
                            or not state.get('deleted'))
                    else:
                        action_button(
                            'switch', 'switch', _('Switch'),
                            disabled=len(modes) < 2 or not rows)
                        action_button(
                            'previous', 'back', _('Previous'),
                            disabled=position <= 1)
                        span(
                            '%s / %s' % (
                                position if position else '_', len(rows)),
                            cls='vs-x2many-badge',
                            title='%s / %s' % (
                                position if position else '_', len(rows)))
                        action_button(
                            'next', 'forward', _('Next'),
                            disabled=not position or position >= len(rows))
                        if has_add_remove:
                            action_button(
                                'remove', 'remove', _('Remove'),
                                disabled=not can_delete or not current_row)
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=_('New'),
                                aria_label=_('New'),
                                disabled=not can_create or None,
                                hx_post=(
                                    X2ManyAction.url(
                                        tab=self.tab['id'],
                                        record=self.record['key'],
                                        field=name,
                                        action='new')
                                    if inline_create and can_create else
                                    OpenRelationNew.url(
                                        tab=self.tab['id'],
                                        record=self.record['key'],
                                        field=name)
                                    if can_create else None),
                                hx_include=(
                                    '#' + entry_id
                                    if has_add_remove else None),
                                hx_target=(
                                    target if inline_create
                                    else '#workspace'),
                                hx_swap='outerHTML',
                                data_x2many_inline_new=(
                                    'true' if inline_create else None)):
                            icon('create')
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=_('Open'),
                                aria_label=_('Open'),
                                disabled=(
                                    not current_row
                                    or (
                                        current_row['id']
                                        and not relation_access['read'])
                                    or (
                                        not current_row['id']
                                        and not can_create)) or None,
                                hx_post=(
                                    (
                                        OpenRelationRecord.url(
                                            tab=self.tab['id'],
                                            model=definition.get('relation'),
                                            record=current_row['id'],
                                            source_record=self.record['key'],
                                            field=name)
                                        if current_row['id'] else
                                        OpenRelationNew.url(
                                            tab=self.tab['id'],
                                            record=self.record['key'],
                                            field=name,
                                            item=current_row['key']))
                                    if current_row and (
                                        (
                                            current_row['id']
                                            and relation_access['read'])
                                        or (
                                            not current_row['id']
                                            and can_create))
                                    else None),
                                hx_target='#workspace',
                                hx_swap='outerHTML'):
                            icon('open')
                        action_button(
                            'delete', 'delete', _('Delete'),
                            disabled=(
                                not can_delete or not current_row
                                or current_row['deleted']))
                        action_button(
                            'undelete', 'undo', _('Undelete'),
                            disabled=not can_delete
                            or not state.get('deleted'))
            with div(
                    cls='vs-x2many-content',
                    style=(
                        'min-height:%spx;max-height:%spx'
                        % (attributes['height'], attributes['height'])
                        if str(attributes.get('height', '')).isdigit()
                        else None)) as content:
                if view_type == 'tree':
                    from .views import ViewRenderer

                    records = {}
                    for row in rows:
                        records[row['key']] = {
                            'key': row['key'],
                            'dom_key': '%s-%s-%s' % (
                                self.record['key'], name, row['key']),
                            'id': row['id'],
                            'values': row['values'],
                            'new': row['id'] is None,
                            'deleted': row['deleted'],
                            }
                    relation_tab = {
                        'id': self.tab['id'],
                        'model': definition['relation'],
                        'exclude_field': (
                            definition.get('relation_field')
                            or getattr(
                                self.Model._fields.get(name), 'field', None)),
                        'records': records,
                        'record_order': [row['key'] for row in rows],
                        'current_record': current,
                        'selected': selected,
                        'expanded': state.setdefault('expanded', []),
                        'column_visibility': state.setdefault(
                            'column_visibility', {}),
                        'access': dict(relation_access),
                        'context': self.tab.get('context', {}),
                        'screen_width': self.tab.get('screen_width'),
                        'focus_record': state.get('_focus_record'),
                        'relation_origin': {
                            'record': self.record['key'],
                            'field': name,
                            'target': target,
                            'editable': not readonly,
                            'type': widget,
                            },
                        }
                    relation_tab['access']['write'] = (
                        relation_tab['access']['write'] and not readonly)
                    relation_tab['access']['create'] = (
                        relation_tab['access']['create'] and not readonly)
                    content.add(ViewRenderer(None).tree(
                            relation_tab, relation_view))
                else:
                    self.x2many_form(
                        name, definition, attributes, relation_view,
                        current_row, readonly, relation_access)
        return control

    def x2many_form(
            self, name, definition, attributes, relation_view,
            current_row, readonly, relation_access):
        # Sao keeps rendering the form view when the relation is empty.  The
        # disabled fields explain what a new row will contain and, crucially,
        # preserve the layout selected by ``mode="form,tree"``.
        from .views import ViewRenderer, parse_architecture

        root = parse_architecture(relation_view)
        values = current_row['values'] if current_row else {}
        record_id = current_row['id'] if current_row else None
        relation_field = (
            definition.get('relation_field')
            or getattr(self.Model._fields.get(name), 'field', None))
        relation_tab = dict(self.tab)
        relation_tab.update({
                'model': definition['relation'],
                'exclude_field': relation_field,
                'relation_origin': {
                    'record': self.record['key'],
                    'field': name,
                    'target': '#' + dom_id(
                        'field', self.tab['id'], self.record['key'], name),
                    'editable': not readonly,
                    },
                '_x2many_form_depth': (
                    self.tab.get('_x2many_form_depth', 0) + 1),
                })
        can_edit = bool(
            current_row and not current_row.get('deleted') and not readonly
            and (
                relation_access['write']
                if current_row.get('id') else relation_access['create']))
        relation_record = {
            'key': current_row['key'] if current_row else 'empty',
            'dom_key': '%s-%s-%s' % (
                self.record['key'], name,
                current_row['key'] if current_row else 'empty'),
            'id': record_id,
            'values': values,
            'new': record_id is None,
            'x2many': {},
            }
        renderer = WidgetRenderer(
            relation_tab, relation_record, relation_view,
            editable=can_edit, endpoint='x2many')
        with div(
                cls='vs-form vs-x2many-form',
                style=ViewRenderer.form_grid_style(
                    root, root.attrib.get('col', 4))) as form:
            ViewRenderer(None).form_children(
                form, root, renderer, relation_tab, relation_record,
                inherited_readonly=not can_edit,
                columns=root.attrib.get('col', 4))

    def selection(self, definition):
        if definition.get('relation'):
            return self.relation_choices(definition, limit=None)
        selection = definition.get('selection') or []
        if isinstance(selection, str):
            dependencies = (
                definition.get('selection_change_with') or [])
            record_values = {}
            for name in dependencies:
                if name == 'id' or name not in self.Model._fields:
                    continue
                value = self.values.get(name)
                field = self.Model._fields[name]
                if (field._type in {'many2one', 'one2one'}
                        and isinstance(value, (list, tuple))):
                    value = value[0] if value else None
                if (field._type in {'many2one', 'one2one'}
                        and value is not None
                        and not isinstance(value, (dict, int))):
                    continue
                record_values[name] = value
            record = self.Model(
                self.record.get('id'), **record_values)
            method = getattr(record, selection, None)
            selection = method() if method else []
        return selection

    def relation_domain(self, definition):
        relation = definition.get('relation')
        if not relation:
            return []
        attributes = next((
                node.attrib for node in self.root.iter('field')
                if node.attrib.get('name') in self.view.get('fields', {})
                and self.view['fields'][node.attrib['name']] is definition), {})
        domain = definition.get('domain', attributes.get('domain')) or []
        add_remove = definition.get(
            'add_remove', attributes.get('add_remove'))
        if isinstance(domain, str) or isinstance(add_remove, str):
            try:
                context = {}
                for name, value in self.values.items():
                    field = self.Model._fields.get(name)
                    if (field and field._type in {'many2one', 'one2one'}
                            and isinstance(value, (list, tuple))):
                        value = value[0] if value else None
                    context[name] = value
                context['id'] = self.record.get('id')
                transaction_context = dict(Transaction().context)
                context['context'] = transaction_context
                context.update(transaction_context)
                decoder = PYSONDecoder(context)
                if isinstance(domain, str):
                    domain = decoder.decode(domain)
                if isinstance(add_remove, str):
                    add_remove = decoder.decode(add_remove)
            except Exception:
                domain = []
                add_remove = None
        if add_remove is not None:
            domain = [domain, add_remove]
        return domain

    def relation_defaults(self, definition):
        """Return values imposed by the domain of a relation field.

        Sao validates each field of a newly-created related record against
        the inverted relation domain.  When the inversion has one possible
        value, it assigns that value before running on-change methods.  The
        server must do the same before it renders the first form fragment.
        """
        relation = definition.get('relation')
        if not relation:
            return {}
        Relation = self.pool.get(relation)
        domain = self.relation_domain(definition)
        defaults = {}
        for name, field in Relation._fields.items():
            inverted = domain_inversion(domain, name, defaults)
            if isinstance(inverted, bool):
                continue
            single_value = field._type not in {
                'dict', 'many2many', 'multiselection', 'one2many'}
            unique, field_name, value = unique_value(
                inverted, single_value=single_value)
            if unique and field_name == name:
                defaults[name] = value
        return defaults

    def relation_choices(self, definition, text=None, limit=100):
        relation = definition.get('relation')
        if not relation:
            return []
        Relation = self.pool.get(relation)
        domain = self.relation_domain(definition)
        try:
            if text:
                return [
                    (value['id'], value['name'])
                    for value in Relation.autocomplete(
                        text, domain, limit)
                    if value.get('id')]
            records = Relation.search(domain, limit=limit)
            return [(record.id, record.rec_name) for record in records]
        except Exception:
            return []

    def relation_title(self, definition, record_id):
        if not record_id:
            return ''
        try:
            return self.pool.get(
                definition['relation'])(int(record_id)).rec_name
        except Exception:
            return ''

    @staticmethod
    def relation_suggestions(
            id_, choices, search_url=None, new_url=None, open_=False,
            modal_target='#modal', input_id=None):
        include = '#' + input_id if input_id else None
        with div(
                id=id_, cls='vs-relation-completion',
                role='listbox',
                data_open=str(bool(open_)).lower()) as suggestions:
            for record_id, title in choices:
                button(
                    title, type='button',
                    cls='vs-relation-option',
                    role='option',
                    data_relation_choice=record_id,
                    data_relation_title=title)
            with div(cls='vs-relation-completion-actions'):
                button(
                    _('Search…'), type='button',
                    cls='vs-relation-completion-action',
                    hx_get=search_url,
                    hx_include=include,
                    hx_target=modal_target,
                    hx_swap='innerHTML')
                if new_url:
                    button(
                        _('Create…'), type='button',
                        cls='vs-relation-completion-action',
                        hx_post=new_url,
                        hx_include=include,
                        hx_target='#workspace',
                        hx_swap='outerHTML')
        return suggestions

    def display(self, name, attributes=None):
        attributes = attributes or {}
        definition = self.view.get('fields', {}).get(name, {})
        widget = attributes.get('widget') or definition.get('type', 'char')
        value = self.values.get(name)
        symbol_value = value
        relation_value = None
        if widget in self.relation_widgets and value:
            try:
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else None
                relation_value = value
                Relation = self.pool.get(definition['relation'])
                value = Relation(int(value)).rec_name
            except Exception:
                pass
        elif widget == 'reference' and value:
            try:
                model, record_id = value.split(',', 1)
                value = self.pool.get(model)(int(record_id)).rec_name
            except Exception:
                pass
        elif widget in self.x2many_widgets:
            value = '(%d)' % len(value or [])
        elif widget in self.binary_widgets:
            size = self.binary_size(value)
            if not size:
                return span('', cls='vs-value vs-tree-binary')
            filename_field = (
                attributes.get('filename')
                or definition.get('filename')
                or getattr(self.Model._fields.get(name), 'filename', None))
            filename = self.values.get(filename_field)
            href = self.binary_href(name, value)
            with span(cls='vs-value vs-tree-binary') as binary:
                span(
                    self.humanize_binary_size(size),
                    cls='vs-tree-binary-size')
                if href:
                    with a(
                            href=href, cls='vs-icon-button',
                            title=_('Save as'), aria_label=_('Save as'),
                            download=filename or None):
                        icon('download')
            return binary
        elif widget in {'selection', 'multiselection'}:
            choices = {
                str(key): title
                for key, title in self.selection(definition)
                }
            if widget == 'multiselection':
                value = ', '.join(
                    choices.get(str(item), stringify(item))
                    for item in (value or []))
            else:
                value = choices.get(str(value), stringify(value))
        elif widget == 'boolean':
            value = '✓' if value else ''
        elif widget == 'dict':
            value = json.dumps(value or {}, ensure_ascii=False, default=str)
        elif widget == 'html':
            return div(value or '', cls='vs-value vs-html')
        elif widget in self.date_widgets and value:
            context = dict(
                self.pool.get('res.user').get_preferences(
                    context_only=True))
            context.update(Transaction().context)
            context.update(decode_value(self.tab.get('context', {})))
            if isinstance(value, datetime):
                value = to_local_datetime(value, context)
            date_format_ = date_format(context)
            time_format_ = self.evaluate(
                definition.get('format'), '%H:%M:%S') or '%H:%M:%S'
            if widget == 'date' and isinstance(value, (date, datetime)):
                value = value.strftime(date_format_)
            elif widget == 'time' and isinstance(value, (time, datetime)):
                value = value.strftime(time_format_)
            elif isinstance(value, datetime):
                value = value.strftime('%s %s' % (
                    date_format_, time_format_))
            elif isinstance(value, date):
                value = value.strftime(date_format_)
            elif isinstance(value, time):
                value = value.strftime(time_format_)
        if (widget in self.numeric_widgets
                and str(attributes.get('grouping', '1')).lower()
                not in {'0', 'false', 'no'}
                and value not in (None, '')):
            try:
                value = format(value, ',')
            except (TypeError, ValueError):
                pass
        symbol, position = self.get_symbol(
            symbol_value, definition, attributes)
        if symbol:
            with span(cls='vs-value vs-monetary-value') as monetary:
                if position < .5:
                    span(symbol, cls='vs-monetary-symbol vs-symbol-start')
                span(stringify(value), cls='vs-monetary-amount')
                if position >= .5:
                    span(symbol, cls='vs-monetary-symbol vs-symbol-end')
            return monetary
        if relation_value and definition.get('relation'):
            relation = definition['relation']
            try:
                relation_id = int(relation_value)
            except (TypeError, ValueError):
                relation_id = None
            ModelAccess = self.pool.get('ir.model.access')
            if (relation_id and relation_id > 0
                    and ModelAccess.get_access(
                        [relation])[relation]['read']):
                OpenRelationRecord = self.pool.get(
                    'cassini.open.relation.record')
                OpenResource = self.pool.get('cassini.open.resource')
                return a(
                    stringify(value), href='#',
                    cls='vs-value vs-tree-relation-link',
                    hx_post=OpenRelationRecord.url(
                        tab=self.tab['id'], model=relation,
                        record=relation_id),
                    hx_target='#workspace', hx_swap='outerHTML',
                    data_relation_open='true',
                    data_open_tab_url=OpenResource.url(
                        model=relation, record=relation_id))
        return span(
            stringify(value),
            cls='vs-value%s' % (
                ' vs-temporal-value' if widget in self.date_widgets else ''))

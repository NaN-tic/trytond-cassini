import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from xml.etree import ElementTree

from dominate.tags import (
    a, button, col, colgroup, div, img, input_, label, option, progress,
    select, span, table, tbody, td, textarea, th, thead, tr, ul)
from trytond.pool import Pool
from trytond.pyson import PYSONDecoder
from trytond.tools import timezone
from trytond.tools.domain_inversion import domain_inversion, unique_value
from trytond.transaction import Transaction

from .icons import icon
from .i18n import translate
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
    textarea_widgets = {'text', 'richtext', 'html'}
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
        self.state_context['id'] = self.record.get('id')
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
        field_id = dom_id('field', self.tab['id'], self.record['key'], name)
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
            wrapper.add(control)
            symbol = attributes.get('symbol')
            if symbol:
                symbol_value = self.values.get(symbol, symbol)
                span(
                    stringify(symbol_value),
                    cls='vs-field-symbol')
        return wrapper

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
            self.text_widgets | self.textarea_widgets | self.date_widgets)
        if self.endpoint == 'preferences':
            UpdateField = self.pool.get(
                'cassini.update.preference.field')
            trigger = 'change'
            synchronization = '#preferences-form:queue last'
            if widget in self.text_widgets | self.textarea_widgets:
                trigger = 'input changed delay:400ms'
            if preserve_self:
                synchronization = 'this:replace'
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
            synchronization = 'closest .vs-wizard:queue last'
            if widget in self.text_widgets | self.textarea_widgets:
                trigger = 'input changed delay:400ms'
            if preserve_self:
                synchronization = 'this:replace'
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
        if self.endpoint != 'record':
            return {}
        UpdateField = self.pool.get('cassini.update.field')
        trigger = 'change'
        synchronization = 'closest .vs-screen:queue last'
        if widget in self.text_widgets | self.textarea_widgets:
            trigger = 'input changed delay:400ms'
        if preserve_self:
            synchronization = 'this:replace'
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

    def common_attributes(
            self, name, field_id, widget, readonly, required):
        values = {
            'id': field_id + '-input',
            'name': 'value' if self.endpoint == 'record' else name,
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

        if widget in self.textarea_widgets:
            return textarea(
                stringify(value), rows=attributes.get('height', 5), **common)

        if widget in self.numeric_widgets:
            step = '1' if widget == 'integer' else 'any'
            factor = float(attributes.get('factor', 1) or 1)
            display_value = value
            if display_value not in (None, '') and factor != 1:
                display_value = (
                    display_value / Decimal(str(factor))
                    if isinstance(display_value, Decimal)
                    else display_value / factor)
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
                if not required and not multiple:
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
                                title=translate('Open the record'),
                                aria_label=translate('Open the record'),
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
                                    title=translate('Clear the field'),
                                    aria_label=translate('Clear the field'),
                                    tabindex='-1',
                                    data_relation_clear='true'):
                                icon('clear')
                    elif not readonly and relation_access['read']:
                        with button(
                                type='button',
                                cls=(
                                    'vs-relation-icon '
                                    'vs-relation-icon-secondary'),
                                title=translate('Search a record'),
                                aria_label=translate('Search a record'),
                                tabindex='-1',
                                hx_get=RelationSearch.url(
                                    tab=self.tab['id'],
                                    record=self.record['key'],
                                    field=name),
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
                        modal_target=modal_target))
            return control

        if widget == 'reference':
            common['placeholder'] = 'model,id'
            return input_(
                type='text', value=stringify(value), **common)

        if widget in self.x2many_widgets:
            return self.x2many(
                name, widget, value, definition, attributes,
                field_id, readonly, required)

        if widget in self.binary_widgets:
            binary_htmx = self.htmx(name, field_id, widget)
            binary_htmx['hx_encoding'] = 'multipart/form-data'
            filename_field = (
                attributes.get('filename')
                or definition.get('filename'))
            filename = self.values.get(filename_field)
            href = None
            if value and self.endpoint == 'record':
                Download = self.pool.get('cassini.download.binary')
                href = Download.url(
                    tab=self.tab['id'], record=self.record['key'],
                    field=name)
            elif value and self.endpoint == 'preferences':
                PreferenceBinary = self.pool.get(
                    'cassini.preference.binary')
                href = PreferenceBinary.url(field=name)
            binary_name = (
                'value' if self.endpoint in {'record', 'wizard'} else name)
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
                                aria_label=translate('Image actions')):
                            if value and href:
                                with a(
                                        href=href,
                                        cls='vs-icon-button',
                                        title=translate('Save as'),
                                        aria_label=translate('Save as'),
                                        download=filename or None):
                                    icon('download')
                            elif not readonly:
                                with label(
                                        cls=(
                                            'vs-icon-button '
                                            'vs-file-select'),
                                        title=translate('Select'),
                                        aria_label=translate('Select')):
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
                                clear_values['hx_vals'] = json.dumps({
                                        binary_name: ''})
                                with button(
                                        type='button',
                                        cls='vs-icon-button',
                                        title=translate('Clear'),
                                        aria_label=translate('Clear'),
                                        **clear_values):
                                    icon('clear')
                return control
            with div(cls='vs-binary') as control:
                if value and href:
                    a(
                        (
                            filename
                            if (filename
                                and str(attributes.get(
                                        'filename_visible', '0')).lower()
                                not in {'0', 'false', 'no'})
                            else translate('Download')),
                        href=href, cls='vs-link')
                if not readonly:
                    input_(
                        id=field_id + '-input',
                        name=binary_name,
                        type='file',
                        cls='vs-input', **binary_htmx)
                    if value:
                        clear_values = self.htmx(
                            name, field_id, widget)
                        clear_values['hx_vals'] = json.dumps({
                                binary_name: ''})
                        button(
                            translate('Clear'), type='button',
                            cls='vs-link-button', **clear_values)
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
            if index < len(view_ids) and view_ids[index].isdigit():
                view_id = int(view_ids[index])
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
        root = ElementTree.fromstring(
            relation_view.get('arch') or '<%s/>' % view_type)
        field_nodes = []
        for node in root.iter('field'):
            name = node.attrib.get('name')
            if (name and name not in {
                        field.attrib.get('name') for field in field_nodes}
                    and str(node.attrib.get(
                            'tree_invisible', '0')).lower()
                    not in {'1', 'true', 'yes'}):
                field_nodes.append(node)
        Relation = self.pool.get(definition['relation'])
        read_fields = [
            node.attrib['name'] for node in field_nodes
            if node.attrib['name'] in Relation._fields
            and Relation._fields[node.attrib['name']]._type != 'binary']
        if 'rec_name' not in read_fields:
            read_fields.append('rec_name')
        ids = [entry['id'] for entry in entries if entry['id']]
        records = {
            record['id']: record
            for record in Relation.read(ids, read_fields)
            } if ids else {}
        for entry in entries:
            item = entry['item']
            if entry['id']:
                entry['values'] = records.get(entry['id'], {})
            elif isinstance(item, dict):
                entry['values'] = decode_value(
                    item.get('values', item))
                entry['values'].setdefault(
                    'rec_name',
                    entry['values'].get(
                        Relation._rec_name, translate('New record')))
            else:
                entry['values'] = {'rec_name': stringify(item)}
        return relation_view, field_nodes, entries

    def x2many_display_value(
            self, definition, name, value, field_definition=None):
        Relation = self.pool.get(definition['relation'])
        field = Relation._fields.get(name)
        if field and field._type == 'boolean':
            return translate('Yes') if value else translate('No')
        if field and field._type in {'many2one', 'one2one'} and value:
            related = {'relation': field.model_name}
            return self.relation_title(related, value)
        field_definition = field_definition or {}
        selection = field_definition.get('selection') or []
        if field and field._type in {'selection', 'multiselection'}:
            titles = dict(selection) if not isinstance(selection, str) else {}
            if field._type == 'multiselection':
                return ', '.join(
                    str(titles.get(item, item)) for item in (value or []))
            return stringify(titles.get(value, value))
        if field and field._type in {'one2many', 'many2many'}:
            return str(len(value or []))
        return stringify(value)

    def x2many(
            self, name, widget, value, definition, attributes,
            field_id, readonly, required):
        X2ManyAction = self.pool.get('cassini.x2many.action')
        OpenRelationNew = self.pool.get(
            'cassini.open.relation.new')
        RelationSearch = self.pool.get(
            'cassini.relation.search')
        OpenRelationRecord = self.pool.get(
            'cassini.open.relation.record')
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
        state = self.record.setdefault(
            'x2many', {}).setdefault(name, {
                'view': 'tree',
                'current': None,
                'deleted': [],
                })
        modes = [
            mode.strip() for mode in attributes.get(
                'mode', 'tree,form').split(',')
            if mode.strip() in {'tree', 'form'}]
        if not modes:
            modes = ['tree']
        view_type = state.get('view')
        if view_type not in modes:
            view_type = modes[0]
            state['view'] = view_type
        relation_view, field_nodes, rows = self.x2many_rows(
            definition, attributes, value, state, view_type)
        row_keys = [row['key'] for row in rows]
        current = state.get('current')
        if current not in row_keys:
            current = row_keys[0] if row_keys else None
            state['current'] = current
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
                cls='vs-x2many-panel',
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
                        aria_label=translate('Relation actions')):
                    action_button(
                        'switch', 'switch', translate('Switch'),
                        disabled=len(modes) < 2 or not rows)
                    action_button(
                        'previous', 'back', translate('Previous'),
                        disabled=position <= 1)
                    span(
                        '%s / %s' % (
                            position if position else '_', len(rows)),
                        cls='vs-x2many-badge',
                        title='%s / %s' % (
                            position if position else '_', len(rows)))
                    action_button(
                        'next', 'forward', translate('Next'),
                        disabled=not position or position >= len(rows))
                    if (widget == 'many2many'
                            or definition.get('add_remove') is not None):
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=translate('Search and add'),
                                aria_label=translate('Search and add'),
                                disabled=(
                                    readonly
                                    or not relation_access['read']) or None,
                                hx_get=(
                                    RelationSearch.url(
                                        tab=self.tab['id'],
                                        record=self.record['key'],
                                        field=name)
                                    if (
                                        not readonly
                                        and relation_access['read'])
                                    else None),
                                hx_target=modal_target,
                                hx_swap='innerHTML'):
                            icon('add')
                        action_button(
                            'remove', 'remove', translate('Remove'),
                            disabled=not can_delete or not current_row)
                    with button(
                            type='button',
                            cls='vs-icon-button',
                            title=translate('New'),
                            aria_label=translate('New'),
                            disabled=not can_create or None,
                            hx_post=(
                                OpenRelationNew.url(
                                    tab=self.tab['id'],
                                    record=self.record['key'],
                                    field=name)
                                if can_create else None),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('create')
                    with button(
                            type='button',
                            cls='vs-icon-button',
                            title=translate('Open'),
                            aria_label=translate('Open'),
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
                        'delete', 'delete', translate('Delete'),
                        disabled=(
                            not can_delete or not current_row
                            or current_row['deleted']))
                    action_button(
                        'undelete', 'undo', translate('Undelete'),
                        disabled=not can_delete
                        or not state.get('deleted'))
            with div(
                    cls='vs-x2many-content',
                    style=(
                        'min-height:%spx;max-height:%spx'
                        % (attributes['height'], attributes['height'])
                        if str(attributes.get('height', '')).isdigit()
                        else None)):
                if view_type == 'tree':
                    self.x2many_tree(
                        definition, relation_view, field_nodes,
                        rows, current, X2ManyAction, name, target)
                else:
                    self.x2many_form(
                        definition, relation_view, field_nodes,
                        current_row)
        return control

    def x2many_tree(
            self, definition, relation_view, field_nodes, rows, current,
            X2ManyAction, name, target):
        OpenRelationRecord = self.pool.get(
            'cassini.open.relation.record')
        ResizeTreeColumns = self.pool.get(
            'cassini.resize.tree.columns')
        columns = field_nodes or [None]
        occurrences = {}
        column_occurrences = []
        for node in columns:
            field_name = (
                node.attrib.get('name') if node is not None
                else 'rec_name')
            occurrences[field_name] = occurrences.get(field_name, 0) + 1
            column_occurrences.append(occurrences[field_name])
        with table(
                cls='vs-x2many-table vs-resizable-table',
                data_column_model=definition.get('relation'),
                data_column_resize_url=ResizeTreeColumns.url()):
            with colgroup():
                for node, occurrence in zip(
                        columns, column_occurrences):
                    field_name = (
                        node.attrib.get('name') if node is not None
                        else 'rec_name')
                    width = (
                        node.attrib.get('width')
                        if node is not None else None)
                    col(
                        style=(
                            'width:%spx' % width
                            if str(width).isdigit() else None),
                        data_column_field=(
                            field_name
                            if field_name != 'rec_name' else None),
                        data_column_occurrence=occurrence)
            with thead():
                with tr():
                    for node, occurrence in zip(
                            columns, column_occurrences):
                        field_name = (
                            node.attrib.get('name') if node is not None
                            else 'rec_name')
                        field_definition = relation_view.get(
                            'fields', {}).get(field_name, {})
                        with th():
                            span((
                                node.attrib.get('string')
                                if node is not None else None)
                                or field_definition.get('string')
                                or translate('Record'))
                            if field_name != 'rec_name':
                                span(
                                    '', cls='vs-column-resizer',
                                    role='separator',
                                    tabindex='0',
                                    aria_label=translate(
                                        'Resize %(column)s column',
                                        column=(
                                            (
                                                node.attrib.get('string')
                                                if node is not None else None)
                                            or field_definition.get('string')
                                            or field_name)),
                                    aria_orientation='vertical',
                                    data_column_resizer='true')
            with tbody():
                for row in rows:
                    with tr(
                            cls='vs-x2many-row%s%s' % (
                                ' vs-x2many-row-current'
                                if row['key'] == current else '',
                                ' vs-x2many-row-deleted'
                                if row['deleted'] else ''),
                            data_x2many_record=row['key']):
                        for column_index, node in enumerate(columns):
                            field_name = (
                                node.attrib.get('name')
                                if node is not None else 'rec_name')
                            title = self.x2many_display_value(
                                definition, field_name,
                                row['values'].get(field_name),
                                relation_view.get(
                                    'fields', {}).get(field_name, {}))
                            with td():
                                if column_index == 0:
                                    button(
                                        title or translate('Record'),
                                        type='button',
                                        cls='vs-x2many-row-button',
                                        hx_post=X2ManyAction.url(
                                            tab=self.tab['id'],
                                            record=self.record['key'],
                                            field=name,
                                            action='select'),
                                        hx_vals=json.dumps({
                                                'item': row['key']}),
                                        hx_target=target,
                                        hx_swap='outerHTML')
                                    if row['id']:
                                        button(
                                            '', type='button',
                                            cls='vs-row-action',
                                            tabindex='-1',
                                            aria_hidden='true',
                                            data_x2many_open_action='true',
                                            hx_post=OpenRelationRecord.url(
                                                tab=self.tab['id'],
                                                model=definition.get(
                                                    'relation'),
                                                record=row['id'],
                                                source_record=(
                                                    self.record['key']),
                                                field=name),
                                            hx_target='#workspace',
                                            hx_swap='outerHTML')
                                else:
                                    span(title)
        if not rows:
            div(translate('No records'), cls='vs-empty')

    def x2many_form(
            self, definition, relation_view, field_nodes, current_row):
        if not current_row:
            div(translate('No record selected'), cls='vs-empty')
            return
        with div(cls='vs-x2many-form'):
            for node in field_nodes:
                name = node.attrib.get('name')
                if not name:
                    continue
                field_definition = relation_view.get(
                    'fields', {}).get(name, {})
                with div(cls='vs-x2many-form-field'):
                    span(
                        node.attrib.get('string')
                        or field_definition.get('string')
                        or name,
                        cls='vs-x2many-form-label')
                    span(self.x2many_display_value(
                            definition, name,
                            current_row['values'].get(name),
                            field_definition))

    def selection(self, definition):
        if definition.get('relation'):
            return self.relation_choices(definition, limit=None)
        selection = definition.get('selection') or []
        if isinstance(selection, str):
            dependencies = (
                definition.get('selection_change_with') or [])
            if dependencies:
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
                    self.record.get('id'),
                    **record_values)
                method = getattr(record, selection, None)
            else:
                method = getattr(self.Model, selection, None)
            selection = method() if method else []
        return selection

    def relation_domain(self, definition):
        relation = definition.get('relation')
        if not relation:
            return []
        domain = definition.get('domain') or []
        add_remove = definition.get('add_remove')
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
            modal_target='#modal'):
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
                    translate('Search…'), type='button',
                    cls='vs-relation-completion-action',
                    hx_get=search_url,
                    hx_target=modal_target,
                    hx_swap='innerHTML')
                if new_url:
                    button(
                        translate('Create…'), type='button',
                        cls='vs-relation-completion-action',
                        hx_post=new_url,
                        hx_target='#workspace',
                        hx_swap='outerHTML')
        return suggestions

    def display(self, name, attributes=None):
        attributes = attributes or {}
        definition = self.view.get('fields', {}).get(name, {})
        widget = attributes.get('widget') or definition.get('type', 'char')
        value = self.values.get(name)
        if widget in self.relation_widgets and value:
            try:
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else None
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
        if (widget in self.numeric_widgets
                and str(attributes.get('grouping', '1')).lower()
                not in {'0', 'false', 'no'}
                and value not in (None, '')):
            try:
                value = format(value, ',')
            except (TypeError, ValueError):
                pass
        return span(stringify(value), cls='vs-value')

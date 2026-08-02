import base64
import calendar as month_calendar
import re
from datetime import date, datetime
from xml.etree import ElementTree

from dominate.tags import (
    a, article, aside, button, col, colgroup, details, div, fieldset, form,
    h2, h3, header, hr, img, input_, label, legend, li, nav, option, p,
    section, select, span, strong, summary, table, tbody, td, th, thead,
    tfoot, tr, ul)
from dominate.util import raw
from trytond.pool import Pool
from trytond.pyson import PYSONEncoder
from trytond.transaction import Transaction

from .engine import combine_domains, evaluate, search_field_definitions
from .icons import filter_icon, icon
from .i18n import translate
from .search import search_domain_parser
from .state import decode_value
from .widgets import HierarchyWidget, WidgetRenderer, dom_id, stringify


def parse_architecture(view):
    architecture = view.get('arch') or '<form/>'
    root = ElementTree.fromstring(architecture)
    fields = view.get('fields', {})
    for node in root.iter():
        name = node.attrib.get('name')
        definition = fields.get(name, {})
        if (
                node.tag not in {'prefix', 'suffix'}
                and 'string' not in node.attrib
                and definition.get('string') is not None):
            node.attrib['string'] = definition['string']
        for attribute in ('states', 'invisible'):
            if (
                    attribute not in node.attrib
                    and definition.get(attribute) is not None):
                value = definition[attribute]
                if attribute == 'states' and not isinstance(value, str):
                    value = PYSONEncoder().encode(value)
                elif not isinstance(value, str):
                    value = '1' if value else '0'
                node.attrib[attribute] = value
    return root


def css_color(value):
    value = str(value or '')
    if re.fullmatch(
            r'(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|'
            r'rgba?\([0-9.,% ]+\)|hsla?\([0-9.,% ]+\))',
            value):
        return value
    return None


def form_accesskey(value):
    for character in str(value or '').lower():
        if character not in {'d', 'e', 'f', 'i', 'n', 't', 'w'}:
            return character
    return None


class ViewRenderer:
    """Render Tryton XML views as server-owned Dominate components."""

    def __init__(self, interface):
        self.interface = interface
        self.pool = Pool()

    def screen(self, tab):
        if tab.get('kind') == 'dashboard':
            return self.dashboard(tab)
        tab = dict(tab)
        tab['screen_width'] = self.interface.data.get('screen_width')
        view = decode_value(tab.get('view', {}))
        screen = section(
            id='screen-' + tab['id'],
            cls='vs-screen',
            hx_sync='body:queue all',
            data_tab=tab['id'],
            data_initial_focus='true',
            data_view=tab.get('view_type'))
        if tab.get('relation_modal'):
            screen.add(self.relation_dialog_header(tab))
        else:
            screen.add(self.toolbar(tab))
        if tab.get('view_type') == 'tree':
            screen.add(self.tree(tab, view))
        elif tab.get('view_type') == 'form':
            screen.add(self.form(tab, view))
        elif tab.get('view_type') == 'list-form':
            screen.add(self.list_form(tab, view))
        elif tab.get('view_type') == 'calendar':
            screen.add(self.calendar(tab, view))
        else:
            screen.add(p(
                    'Unsupported view: %s' % tab.get('view_type'),
                    cls='vs-notice vs-notice-error'))
        if tab.get('relation_modal'):
            screen.add(self.relation_dialog_actions(tab))
        return screen

    def dashboard(self, tab):
        ReloadTab = self.pool.get('cassini.reload.tab')
        with section(
                id='screen-' + tab['id'],
                cls='vs-screen vs-dashboard-screen',
                data_tab=tab['id'],
                data_view='dashboard') as screen:
            with header(cls='vs-toolbar vs-dashboard-toolbar'):
                h2(tab['title'], cls='vs-dashboard-title')
                with button(
                        type='button',
                        cls='vs-icon-button',
                        title=translate('Reload/Undo'),
                        aria_label=translate('Reload/Undo'),
                        hx_post=ReloadTab.url(tab=tab['id']),
                        hx_target='#screen-' + tab['id'],
                        hx_swap='outerHTML'):
                    icon('refresh')
            self.dashboard_items(
                decode_value(tab.get('dashboard_items', [])))
        return screen

    def dashboard_items(self, items):
        with div(cls='vs-dashboard-grid') as grid:
            for item in items:
                colspan = max(1, min(4, int(item.get('colspan') or 1)))
                height = max(120, int(item.get('height') or 450))
                chart = str(item.get('chart') or '')
                payload = base64.b64encode(
                    chart.encode('utf-8')).decode('ascii')
                with article(
                        cls='vs-dashboard-item',
                        style=(
                            'grid-column:span %d;min-height:%dpx'
                            % (colspan, height))):
                    div(
                        cls='vs-chart',
                        data_cassini_chart='true',
                        data_chart_payload=payload,
                        style='min-height:%dpx' % height,
                        role='img',
                        aria_label=translate('Dashboard chart'))
                    children = item.get('children') or []
                    if children:
                        self.dashboard_items(children)
        return grid

    def relation_dialog_header(self, tab):
        DeleteRecords = self.pool.get('cassini.delete.records')
        NewRecord = self.pool.get('cassini.new.record')
        SelectNeighbor = self.pool.get('cassini.select.neighbor')
        SwitchView = self.pool.get('cassini.switch.view')
        current = tab.get('current_record')
        record_order = tab.get('record_order', [])
        position = (
            record_order.index(current) + 1
            if tab.get('relation_navigation')
            and current in record_order else 0)
        with header(cls='vs-relation-dialog-header') as header_:
            h2(tab['title'], cls='vs-relation-dialog-title')
            if tab.get('resource_modal'):
                access = tab.get('access', {})
                view_types = tab.get('view_types', [])
                current_view = tab.get('view_type')
                next_view = (
                    view_types[
                        (view_types.index(current_view) + 1)
                        % len(view_types)]
                    if current_view in view_types and view_types else '')
                with div(
                        cls='vs-relation-dialog-resource-actions',
                        role='group',
                        aria_label=translate('Resource actions')):
                    with button(
                            type='button', cls='vs-icon-button',
                            title=translate('New'),
                            aria_label=translate('New'),
                            disabled=not access.get('create', True) or None,
                            hx_post=NewRecord.url(tab=tab['id']),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('create')
                    with button(
                            type='button', cls='vs-icon-button',
                            title=translate('Delete'),
                            aria_label=translate('Delete'),
                            disabled=(
                                not current
                                or not access.get('delete', True) or None),
                            hx_confirm=translate(
                                'Delete the selected records?'),
                            hx_post=DeleteRecords.url(tab=tab['id']),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('delete')
                    with button(
                            type='button', cls='vs-icon-button',
                            title=translate('Switch view'),
                            aria_label=translate('Switch view'),
                            disabled=len(view_types) < 2 or None,
                            hx_post=SwitchView.url(
                                tab=tab['id'], view=next_view),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('switch')
            if tab.get('relation_navigation'):
                with div(
                        cls='vs-relation-navigation',
                        role='group',
                        aria_label=translate('Relation actions')):
                    with button(
                            type='button', cls='vs-icon-button',
                            title=translate('Previous'),
                            aria_label=translate('Previous'),
                            disabled=(not position or position <= 1) or None,
                            hx_post=SelectNeighbor.url(
                                tab=tab['id'], direction='previous'),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('back')
                    span(
                        '%s / %s' % (
                            position if position else '_',
                            len(record_order)),
                        cls='vs-relation-navigation-position')
                    with button(
                            type='button', cls='vs-icon-button',
                            title=translate('Next'),
                            aria_label=translate('Next'),
                            disabled=(
                                not position
                                or position >= len(record_order)) or None,
                            hx_post=SelectNeighbor.url(
                                tab=tab['id'], direction='next'),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('forward')
        return header_

    def relation_dialog_actions(self, tab):
        CloseTab = self.pool.get('cassini.close.tab')
        SaveRecords = self.pool.get('cassini.save.records')
        with div(cls='vs-dialog-actions vs-relation-dialog-actions') as tag:
            button(
                translate('Cancel'), type='button', cls='vs-button',
                data_modal_cancel='true',
                hx_post=CloseTab.url(tab=tab['id']),
                hx_target='#workspace', hx_swap='outerHTML')
            button(
                translate('OK'), type='button',
                cls='vs-button vs-button-primary',
                hx_post=SaveRecords.url(tab=tab['id']),
                hx_target='#workspace', hx_swap='outerHTML')
        return tag

    def toolbar(self, tab):
        NewRecord = self.pool.get('cassini.new.record')
        CloseTab = self.pool.get('cassini.close.tab')
        DeleteRecords = self.pool.get('cassini.delete.records')
        DuplicateRecord = self.pool.get('cassini.duplicate.record')
        ReloadTab = self.pool.get('cassini.reload.tab')
        RevertRecord = self.pool.get('cassini.revert.record')
        RunButton = self.pool.get('cassini.run.button')
        SaveRecords = self.pool.get('cassini.save.records')
        ShowRevisions = self.pool.get('cassini.show.revisions')
        SelectNeighbor = self.pool.get('cassini.select.neighbor')
        SwitchView = self.pool.get('cassini.switch.view')
        SwitchDomain = self.pool.get('cassini.switch.domain')
        ExportRecords = self.pool.get('cassini.export.records')
        ImportRecords = self.pool.get('cassini.import.records')
        OpenRelated = self.pool.get('cassini.open.related')
        AttachmentData = self.pool.get('cassini.attachment.data')
        AttachmentPreview = self.pool.get('cassini.attachment.preview')
        AttachmentUpload = self.pool.get('cassini.attachment.upload')
        RunToolbarAction = self.pool.get('cassini.toolbar.action')

        current = tab.get('current_record')
        record = tab.get('records', {}).get(current) if current else None
        record_order = tab.get('record_order', [])
        relation_position = (
            record_order.index(current) + 1
            if tab.get('relation_navigation')
            and current in record_order else 0)
        record_position = (
            record_order.index(current) + 1
            if current in record_order else 0)
        selected_count = len([
                key for key in tab.get('selected', [])
                if key in record_order])
        loaded_count = int(tab.get('offset') or 0) + len(record_order)
        total_count = int(tab.get('count') or len(record_order))
        record_status = str(
            int(tab.get('offset') or 0) + record_position
            if record_position else '_')
        if selected_count > 1:
            record_status += '#%s' % selected_count
        if loaded_count < total_count:
            record_status += '@%s/%s' % (loaded_count, total_count)
        else:
            record_status += '/%s' % loaded_count
        access = tab.get('access', {
                'read': True, 'write': True,
                'create': True, 'delete': True})
        revision = decode_value(
            tab.get('context', {})).get('_datetime')
        view_types = tab.get('view_types', [])
        if tab.get('view_type') in view_types:
            view_index = view_types.index(tab['view_type'])
            next_view = view_types[(view_index + 1) % len(view_types)]
        else:
            next_view = view_types[0] if view_types else ''
        dirty_records = [
            item for item in tab.get('records', {}).values()
            if item.get('dirty')]
        can_save = all(
            access['create'] if item.get('new') else access['write']
            for item in dirty_records)
        view = decode_value(tab.get('view', {}))
        root = parse_architecture(view)
        view_creatable = str(
            root.attrib.get('creatable', '1')).lower() not in {
                '0', 'false', 'no'}
        toolbar_data = decode_value(tab.get('toolbar', {}))
        renderer = (
            WidgetRenderer(tab, record, view, editable=False)
            if record else None)
        view_buttons = list(root.iter('button'))
        resource_counts = {
            'attachment_count': 0,
            'note_count': 0,
            'note_unread': 0,
            }
        attachments = []
        if record and record.get('id'):
            Model = self.pool.get(tab['model'])
            resource = Model(record['id'])
            resource_counts.update(resource.resources())
            Attachment = self.pool.get('ir.attachment')
            attachments = Attachment.search([
                    ('resource', '=', str(resource)),
                    ], limit=20)

        def action_definitions(category):
            items = []
            for node in view_buttons:
                attributes = dict(node.attrib)
                if attributes.get('keyword', 'action') != category:
                    continue
                readonly = not bool(record)
                invisible = False
                if renderer:
                    state_readonly, _, invisible = renderer.states(
                        {}, attributes)
                    readonly = readonly or state_readonly
                multiple = str(
                    attributes.get('multiple', '0')).lower() in {
                        '1', 'true', 'yes'}
                if multiple and not tab.get('selected'):
                    readonly = True
                if invisible:
                    continue
                title = (
                    attributes.get('string')
                    or attributes.get('name')
                    or translate('Action'))
                items.append({
                        'title': title,
                        'icon': attributes.get('icon'),
                        'disabled': readonly,
                        'confirm': attributes.get('confirm'),
                        'url': RunButton.url(
                            tab=tab['id'],
                            button=attributes.get('name', ''),
                            kind=attributes.get('type', 'class'),
                            record=current),
                        })
            for action in toolbar_data.get(category, []):
                items.append({
                        'title': action['name'],
                        'icon': action.get('icon'),
                        'href': False,
                        'url': RunToolbarAction.url(
                            tab=tab['id'], action=action['id']),
                        })
            return items

        controls = (
            ('create', translate('New'), NewRecord.url(tab=tab['id']),
                not access['create'] or not view_creatable
                or bool(revision), None),
            ('save', translate('Save'), SaveRecords.url(tab=tab['id']),
                not tab.get('dirty') or not can_save or bool(revision),
                None),
            ('refresh', translate('Reload/Undo'), (
                    RevertRecord.url(
                        tab=tab['id'], record=current)
                    if record and record.get('dirty')
                    else ReloadTab.url(tab=tab['id'])),
                False, (
                    translate('Discard the unsaved changes to this record?')
                    if record and record.get('dirty') else None)),
            ('copy', translate('Duplicate'),
                DuplicateRecord.url(tab=tab['id']),
                not record or record.get('new')
                or not access['create'] or bool(revision), None),
            ('delete', translate('Delete'),
                DeleteRecords.url(tab=tab['id']),
                not record or not access['delete'] or bool(revision),
                translate('Delete the selected records?')),
            )
        with div(
                id='toolbar-' + tab['id'],
                cls='vs-toolbar') as toolbar:
            window_heading = div(cls='vs-window-heading')
            toolbar.add(window_heading)
            with window_heading:
                with details(
                        cls='vs-popup vs-window-menu') as window_menu:
                    with summary(
                            cls='vs-window-title',
                            title=translate('Window actions'),
                            aria_label='%s: %s' % (
                                translate('Window actions'), tab['title'])):
                        span('', cls='vs-window-title-caret')
                    with div(
                            cls='vs-popup-menu vs-window-menu-list',
                            role='menu') as window_menu_list:
                        with button(
                                type='button',
                                cls='vs-popup-item vs-popup-item-icon',
                                role='menuitem',
                                disabled=len(view_types) < 2 or None,
                                data_shortcut_action='switch',
                                data_next_view=next_view,
                                hx_post=SwitchView.url(
                                    tab=tab['id'], view=next_view),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon('switch')
                            span(translate('Switch view'))
                    window_menu.add(window_menu_list)
                    for direction, image, title in (
                            ('previous', 'back', translate('Previous')),
                            ('next', 'forward', translate('Next'))):
                        with button(
                                type='button',
                                cls=(
                                    'vs-popup-item '
                                    'vs-popup-item-icon'),
                                role='menuitem',
                                disabled=(
                                    not tab.get('record_order') or None),
                                data_shortcut_action=direction,
                                hx_post=SelectNeighbor.url(
                                    tab=tab['id'], direction=direction),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon(image)
                            span(title)
                    with button(
                            type='button',
                            cls='vs-popup-item vs-popup-item-icon',
                            role='menuitem',
                            data_shortcut_action='search'):
                        icon('search')
                        span(translate('Search'))
                    span(translate('Records'), cls='vs-popup-heading')
                    for image, title, url, disabled, confirm in controls:
                        with button(
                                type='button',
                                cls=(
                                    'vs-popup-item '
                                    'vs-popup-item-icon'),
                                role='menuitem',
                                disabled=disabled or None,
                                data_shortcut_action={
                                    'create': 'new',
                                    'save': 'save',
                                    'refresh': 'reload',
                                    'copy': 'duplicate',
                                    'delete': 'delete',
                                    }[image],
                                hx_confirm=confirm,
                                hx_post=url,
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon(image)
                            span(title)
                    with button(
                            type='button',
                            cls='vs-popup-item vs-popup-item-icon',
                            role='menuitem',
                            disabled=(
                                not record or record.get('new') or None),
                            hx_post=OpenRelated.url(
                                tab=tab['id'], resource='logs'),
                            hx_target='#workspace',
                            hx_swap='outerHTML',
                            hx_push_url='true'):
                        icon('log')
                        span(translate('View logs'))
                    if tab.get('history'):
                        with button(
                                type='button',
                                cls='vs-popup-item vs-popup-item-icon',
                                role='menuitem',
                                disabled=(
                                    not record or record.get('new') or None),
                                hx_get=ShowRevisions.url(tab=tab['id']),
                                hx_target='#modal',
                                hx_swap='innerHTML'):
                            icon('history')
                            span(translate('Revisions'))
                    for resource, image, title in (
                            ('attachments', 'attach',
                                translate('Attachments')),
                            ('notes', 'note', translate('Notes'))):
                        with button(
                                type='button',
                                cls='vs-popup-item vs-popup-item-icon',
                                role='menuitem',
                                disabled=(
                                    not record or record.get('new') or None),
                                hx_post=OpenRelated.url(
                                    tab=tab['id'], resource=resource),
                                hx_target='#workspace',
                                hx_swap='outerHTML',
                                hx_push_url='true'):
                            icon(image)
                            span(title)
                    for category, image, title in (
                            ('action', 'launch', translate('Action')),
                            ('relate', 'link', translate('Relate')),
                            ('print', 'print', translate('Print'))):
                        items = action_definitions(category)
                        if items:
                            with button(
                                    type='button',
                                    cls=(
                                        'vs-popup-item '
                                        'vs-popup-item-icon'),
                                    role='menuitem',
                                    data_open_toolbar_popup=category):
                                icon(image)
                                span(title)
                    span(translate('Data'), cls='vs-popup-heading')
                    with a(
                            href=ExportRecords.url(tab=tab['id']),
                            cls='vs-popup-item vs-popup-item-icon',
                            role='menuitem'):
                        icon('export')
                        span(translate('Export selected fields'))
                    for export in toolbar_data.get('exports', []):
                        with a(
                                href=ExportRecords.url(
                                    tab=tab['id'],
                                    export_id=export['id']),
                                cls=(
                                    'vs-popup-item '
                                    'vs-popup-item-icon'),
                                role='menuitem'):
                            icon('export')
                            span(export['name'])
                    with form(
                            cls='vs-import-form vs-popup-import',
                            hx_post=ImportRecords.url(tab=tab['id']),
                            hx_encoding='multipart/form-data',
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        with label(
                                cls=(
                                    'vs-popup-item '
                                    'vs-popup-item-icon'),
                                html_for='import-' + tab['id'],
                                role='menuitem'):
                            icon('import')
                            span(translate('Import'))
                        input_(
                            id='import-' + tab['id'], type='file',
                            name='file', accept='.csv,text/csv',
                            cls='vs-file-input',
                            disabled=(
                                not access['create']
                                or bool(revision) or None),
                            hx_post=ImportRecords.url(tab=tab['id']),
                            hx_trigger='change',
                            hx_encoding='multipart/form-data',
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML',
                            hx_include='this')
                    with button(
                            type='button',
                            cls='vs-popup-item vs-popup-item-icon',
                            role='menuitem',
                            data_shortcut_action='close',
                            hx_post=CloseTab.url(tab=tab['id']),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('close')
                        span(translate('Close tab'))
                    for menu_item in list(window_menu.children[2:]):
                        window_menu_list.add(menu_item)
                    del window_menu.children[2:]
                    window_heading.add(window_menu)
                with div(cls='vs-window-heading-label'):
                    span(tab['title'], cls='vs-window-title-text')
                    if tab.get('dirty'):
                        span(
                            '•', cls='vs-window-dirty',
                            title=translate('Unsaved'))
                        span(
                            translate('Unsaved changes'),
                            cls='vs-window-dirty-status')

            with div(cls='vs-toolbar-actions'):
                if tab.get('relation_navigation'):
                    with div(
                            cls=(
                                'vs-toolbar-group '
                                'vs-relation-navigation'),
                            role='group',
                            aria_label=translate('Relation actions')):
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=translate('Previous'),
                                aria_label=translate('Previous'),
                                disabled=(
                                    not relation_position
                                    or relation_position <= 1) or None,
                                hx_post=SelectNeighbor.url(
                                    tab=tab['id'], direction='previous'),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon('back')
                        span(
                            '%s / %s' % (
                                relation_position
                                if relation_position else '_',
                                len(record_order)),
                            cls='vs-relation-navigation-position')
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=translate('Next'),
                                aria_label=translate('Next'),
                                disabled=(
                                    not relation_position
                                    or relation_position
                                    >= len(record_order)) or None,
                                hx_post=SelectNeighbor.url(
                                    tab=tab['id'], direction='next'),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon('forward')
                with button(
                        type='button',
                        cls='vs-icon-button',
                        title=translate('Switch view'),
                        aria_label=translate('Switch view'),
                        disabled=len(view_types) < 2 or None,
                        data_shortcut_action='switch',
                        data_next_view=next_view,
                        hx_post=SwitchView.url(
                            tab=tab['id'], view=next_view),
                        hx_target='#screen-' + tab['id'],
                        hx_swap='outerHTML'):
                    icon('switch')
                if not tab.get('relation_navigation'):
                    with div(
                            cls=(
                                'vs-toolbar-group '
                                'vs-record-navigation'),
                            role='group',
                            aria_label=translate('Record navigation')):
                        with button(
                                type='button', cls='vs-icon-button',
                                title=translate('Previous record'),
                                aria_label=translate('Previous record'),
                                disabled=(
                                    not record_position
                                    or record_position <= 1) or None,
                                data_shortcut_action='previous',
                                hx_post=SelectNeighbor.url(
                                    tab=tab['id'], direction='previous'),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon('back')
                        span(
                            record_status,
                            cls='vs-relation-navigation-position '
                                'vs-record-navigation-position')
                        with button(
                                type='button', cls='vs-icon-button',
                                title=translate('Next record'),
                                aria_label=translate('Next record'),
                                disabled=(
                                    not record_position
                                    or record_position
                                    >= len(record_order)) or None,
                                data_shortcut_action='next',
                                hx_post=SelectNeighbor.url(
                                    tab=tab['id'], direction='next'),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon('forward')
                with div(cls='vs-toolbar-group', role='group'):
                    for (
                            image, title, url,
                            disabled, confirm) in controls[:3]:
                        with button(
                                type='button',
                                cls='vs-icon-button%s' % (
                                    ' vs-button-primary'
                                    if image == 'save' else ''),
                                title=title, aria_label=title,
                                disabled=disabled or None,
                                data_shortcut_action={
                                    'create': 'new',
                                    'save': 'save',
                                    'refresh': 'reload',
                                    }[image],
                                hx_confirm=confirm,
                                hx_post=url,
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML'):
                            icon(image)
                with div(
                        cls='vs-toolbar-group vs-toolbar-secondary',
                        role='group'):
                    if record and record.get('id'):
                        attachment_count = resource_counts[
                            'attachment_count']
                        with details(
                                cls=(
                                    'vs-popup vs-resource-popup '
                                    'vs-attachment-popup'),
                                data_attachment_drop='true'):
                            with summary(
                                    cls='vs-icon-button',
                                    title=(
                                        '%s (%s)' % (
                                            translate('Attachments'),
                                            attachment_count)
                                        if attachment_count else
                                        translate('Attachments')),
                                    aria_label=(
                                        '%s (%s)' % (
                                            translate('Attachments'),
                                            attachment_count)
                                        if attachment_count else
                                        translate('Attachments')),
                                    data_shortcut_action='attach'):
                                icon('attach')
                                if attachment_count:
                                    span(
                                        '99+' if attachment_count > 99
                                        else str(attachment_count),
                                        cls='vs-resource-badge',
                                        aria_hidden='true')
                                span(
                                    '▾', cls='vs-popup-caret',
                                    aria_hidden='true')
                            with div(
                                    cls='vs-popup-menu', role='menu'):
                                for attachment in attachments:
                                    with a(
                                            href=(
                                                attachment.link
                                                if attachment.type == 'link'
                                                else AttachmentData.url(
                                                    tab=tab['id'],
                                                    attachment=attachment.id)),
                                            target='_blank',
                                            rel='noreferrer noopener',
                                            cls=(
                                                'vs-popup-item '
                                                'vs-popup-item-icon'),
                                            role='menuitem'):
                                        icon(
                                            'link'
                                            if attachment.type == 'link'
                                            else 'attach')
                                        span(attachment.name)
                                if attachments:
                                    hr(cls='vs-popup-separator')
                                with form(
                                        cls='vs-attachment-upload-form',
                                        hx_post=AttachmentUpload.url(
                                            tab=tab['id']),
                                        hx_encoding='multipart/form-data',
                                        hx_target='#screen-' + tab['id'],
                                        hx_swap='outerHTML'):
                                    with label(
                                            cls=(
                                                'vs-popup-item '
                                                'vs-popup-item-icon%s' % (
                                                    ' vs-popup-item-disabled'
                                                    if (not access['write']
                                                        or revision)
                                                    else '')),
                                            role='menuitem'):
                                        icon('create')
                                        span(translate('Add...'))
                                        input_(
                                            type='file', name='attachments',
                                            multiple=True,
                                            cls='vs-file-input',
                                            disabled=(
                                                not access['write']
                                                or bool(revision) or None),
                                            data_attachment_input='true',
                                            hx_post=AttachmentUpload.url(
                                                tab=tab['id']),
                                            hx_trigger='change',
                                            hx_encoding=(
                                                'multipart/form-data'),
                                            hx_target=(
                                                '#screen-' + tab['id']),
                                            hx_swap='outerHTML',
                                            hx_include='this')
                                with button(
                                        type='button',
                                        cls=(
                                            'vs-popup-item '
                                            'vs-popup-item-icon'),
                                        role='menuitem',
                                        disabled=not attachments or None,
                                        hx_get=AttachmentPreview.url(
                                            tab=tab['id']),
                                        hx_target='#modal',
                                        hx_swap='innerHTML'):
                                    icon('open')
                                    span(translate('Preview'))
                                with button(
                                        type='button',
                                        cls=(
                                            'vs-popup-item '
                                            'vs-popup-item-icon'),
                                        role='menuitem',
                                        hx_post=OpenRelated.url(
                                            tab=tab['id'],
                                            resource='attachments'),
                                        hx_target='#workspace',
                                        hx_swap='outerHTML'):
                                    icon('menu')
                                    span(translate('Manage...'))
                    else:
                        with button(
                                type='button', cls='vs-icon-button',
                                title=translate('Attachments'),
                                aria_label=translate('Attachments'),
                                disabled=True,
                                data_shortcut_action='attach'):
                            icon('attach')
                    note_count = resource_counts['note_count']
                    note_unread = resource_counts['note_unread']
                    note_title = (
                        '%s (%s/%s)' % (
                            translate('Notes'), note_unread, note_count)
                        if note_unread else
                        '%s (%s)' % (translate('Notes'), note_count)
                        if note_count else translate('Notes'))
                    with button(
                            type='button',
                            cls='vs-icon-button vs-resource-button',
                            title=note_title,
                            aria_label=note_title,
                            disabled=(
                                not record or record.get('new') or None),
                            data_shortcut_action='note',
                            hx_post=OpenRelated.url(
                                tab=tab['id'], resource='notes'),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('note')
                        if note_count:
                            note_label = (
                                '%s/%s' % (
                                    '99+' if note_unread > 99
                                    else note_unread,
                                    '99+' if note_count > 99
                                    else note_count)
                                if note_unread else
                                ('99+' if note_count > 99
                                    else str(note_count)))
                            span(
                                note_label,
                                cls='vs-resource-badge%s' % (
                                    ' vs-resource-badge-unread'
                                    if note_unread else ''),
                                aria_hidden='true')
                    for category, image, title in (
                            ('action', 'launch', translate('Action')),
                            ('relate', 'link', translate('Relate')),
                            ('print', 'print', translate('Print'))):
                        items = action_definitions(category)
                        with details(
                                cls='vs-popup vs-action-popup',
                                data_action_category=category):
                            with summary(
                                    cls='vs-icon-button',
                                    title=title, aria_label=title,
                                    data_shortcut_action=category):
                                icon(image)
                                span(
                                    '▾', cls='vs-popup-caret',
                                    aria_hidden='true')
                            with div(cls='vs-popup-menu', role='menu'):
                                if items:
                                    for item in items:
                                        if item.get('href'):
                                            a(
                                                item['title'],
                                                href=item['url'],
                                                cls='vs-popup-item',
                                                role='menuitem')
                                        else:
                                            with button(
                                                    type='button',
                                                    cls=(
                                                        'vs-popup-item '
                                                        'vs-popup-item-icon'),
                                                    role='menuitem',
                                                    disabled=(
                                                        item.get('disabled')
                                                        or None),
                                                    hx_confirm=item.get(
                                                        'confirm'),
                                                    hx_post=item['url'],
                                                    hx_target='#workspace',
                                                    hx_swap='outerHTML'):
                                                if item.get('icon'):
                                                    icon(item['icon'].removeprefix(
                                                            'tryton-'))
                                                span(item['title'])
                                else:
                                    span(
                                        translate('No actions'),
                                        cls='vs-popup-empty')
                    if tab.get('relation_modal'):
                        with button(
                                type='button',
                                cls='vs-icon-button',
                                title=translate('Close'),
                                aria_label=translate('Close'),
                                hx_post=CloseTab.url(tab=tab['id']),
                                hx_target='#workspace',
                                hx_swap='outerHTML'):
                            icon('close')
            if revision:
                span(
                    'Revision %s' % stringify(revision),
                    cls='vs-revision')

            domains = decode_value(tab.get('domain_tabs', []))
            domain_counts = decode_value(tab.get('domain_counts', []))
            if domains:
                with nav(
                        cls=(
                            'vs-domain-tabs vs-local-tabs '
                            'vs-tab-strip'),
                        aria_label=translate('Domains')):
                    with ul(cls='vs-tab-list', role='tablist'):
                        for index, domain in enumerate(domains):
                            selected = (
                                index == tab.get('active_domain', 0))
                            with li(
                                    role='presentation',
                                    cls='vs-local-tab%s' % (
                                        ' vs-local-tab-active'
                                        if selected else '')):
                                with button(
                                        type='button', role='tab',
                                        aria_selected=str(selected).lower(),
                                        cls='vs-local-tab-title',
                                        hx_post=SwitchDomain.url(
                                            tab=tab['id'], domain=index),
                                        hx_target='#screen-' + tab['id'],
                                        hx_swap='outerHTML'):
                                    span(domain['name'])
                                    count = (
                                        domain_counts[index]
                                        if index < len(domain_counts)
                                        else None)
                                    if domain.get('count') and count is not None:
                                        span(
                                            '99+' if count > 99 else str(count),
                                            cls='vs-domain-count',
                                            title=(
                                                '%s+' if count >= 1000
                                                else '%s') % count,
                                            aria_hidden='true')
        if tab.get('view_type') in {'tree', 'calendar', 'list-form'}:
            toolbar.add(self.search_toolbar(tab))
        return toolbar

    def search_toolbar(self, tab):
        Search = self.pool.get('cassini.search')
        SearchDraft = self.pool.get('cassini.search.draft')
        ToggleActive = self.pool.get('cassini.toggle.active')
        ApplySearchBookmark = self.pool.get(
            'cassini.apply.search.bookmark')
        ViewSearch = self.pool.get('ir.ui.view_search')

        view = decode_value(tab.get('view', {}))
        definitions = search_field_definitions(view)
        search_filters = decode_value(tab.get('search_filters', {}))
        search_domain = decode_value(tab.get('search_domain', []))
        bookmarks = ViewSearch.get().get(tab['model'], [])
        bookmark_id = int(tab.get('search_bookmark') or 0)
        current_bookmark = next((
                bookmark for bookmark in bookmarks
                if int(bookmark[0]) == bookmark_id), None)
        if current_bookmark is None:
            current_bookmark = next((
                bookmark for bookmark in bookmarks
                if tab.get('search_draft', tab.get('search', ''))
                == tab.get('search', '')
                if (PYSONEncoder().encode(bookmark[2])
                    == PYSONEncoder().encode(search_domain))), None)

        with div(
                cls='vs-search-toolbar',
                style=(
                    'display:flex;min-width:100%;width:100%;'
                    'flex:0 0 100%;order:20')) as search_toolbar:
            with details(cls='vs-popup vs-filter-popup'):
                with summary(
                        cls='vs-icon-button',
                        title=translate('Filters'), aria_label=translate('Filters')):
                    filter_icon()
                with div(
                        cls='vs-popup-menu vs-filter-menu',
                        role='dialog', aria_label=translate('Filters')):
                    with form(
                            cls='vs-filter-form',
                            hx_post=Search.url(tab=tab['id']),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        for name, definition in definitions.items():
                            if ('.' in name
                                    or definition.get('searchable') is False
                                    or definition.get('type') in {
                                        'binary', 'image', 'document',
                                        'dict', 'one2many', 'many2many'}):
                                continue
                            self.search_filter_control(
                                name, definition,
                                self.search_selection(
                                    tab, name, definition),
                                search_filters.get(name, {}))
                        with div(cls='vs-dialog-actions'):
                            button(
                                translate('Find'), type='submit',
                                cls='vs-button vs-button-primary')
            query_group = div(cls='vs-search-query-group')
            search_toolbar.add(query_group)
            search_form = form(
                cls='vs-search-form',
                hx_post=Search.url(tab=tab['id']),
                hx_target='#screen-' + tab['id'],
                hx_swap='outerHTML')
            query_group.add(search_form)
            with search_form:
                input_(
                    type='search', name='query',
                    id='search-input-' + tab['id'],
                    value=tab.get(
                        'search_draft', tab.get('search', '')),
                    placeholder=translate('Search'),
                    autocomplete='off',
                    cls='vs-search-input',
                    data_search_autocomplete='true',
                    aria_autocomplete='list',
                    aria_controls='search-completion-' + tab['id'],
                    aria_expanded='false',
                    hx_trigger='input changed delay:350ms',
                    hx_post=SearchDraft.url(tab=tab['id']),
                    hx_target='#search-completion-' + tab['id'],
                    hx_swap='outerHTML',
                    hx_sync='this:replace',
                    hx_preserve='true')
                self.search_completion(tab)
                with button(
                        type='submit', cls='vs-icon-button',
                        title=translate('Search'), aria_label=translate('Search')):
                    icon('search')
            bookmark_control = self.search_bookmark_control(
                tab, current_bookmark)
            query_group.add(bookmark_control)
            bookmark_popup = details(cls='vs-popup vs-bookmark-popup')
            query_group.add(bookmark_popup)
            with bookmark_popup:
                with summary(
                        cls='vs-icon-button',
                        title=translate('Bookmarks'), aria_label=translate('Bookmarks')):
                    icon('bookmarks')
                with div(cls='vs-popup-menu', role='menu'):
                    if bookmarks:
                        for bookmark_id, name, _domain, _access in bookmarks:
                            button(
                                name, type='button',
                                cls='vs-popup-item',
                                role='menuitem',
                                hx_post=ApplySearchBookmark.url(
                                    tab=tab['id'],
                                    bookmark=bookmark_id),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML')
                    else:
                        span(translate('No bookmarks'), cls='vs-popup-empty')
            with button(
                    type='button',
                    cls='vs-icon-button%s' % (
                        ' vs-button-active'
                        if tab.get('active_only', True) else ''),
                    title=(
                        translate('Show inactive records')
                        if tab.get('active_only', True)
                        else translate('Show active records')),
                    aria_label=(
                        translate('Show inactive records')
                        if tab.get('active_only', True)
                        else translate('Show active records')),
                    hx_post=ToggleActive.url(tab=tab['id']),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML'):
                icon(
                    'archive'
                    if tab.get('active_only', True)
                    else 'unarchive')
            pagination = self.search_pagination(tab)
            search_toolbar.add(pagination)
        return search_toolbar

    def search_bookmark_control(self, tab, current_bookmark=None):
        SearchBookmarkDialog = self.pool.get(
            'cassini.search.bookmark.dialog')
        DeleteSearchBookmark = self.pool.get(
            'cassini.delete.search.bookmark')
        search_domain = decode_value(tab.get('search_domain', []))
        current_draft = tab.get('search_draft', tab.get('search', ''))
        if current_draft != tab.get('search', ''):
            current_bookmark = None
        if current_bookmark and current_bookmark[3]:
            with button(
                    type='button', cls='vs-icon-button',
                    id='search-bookmark-control-' + tab['id'],
                    title=translate('Remove this bookmark'),
                    aria_label=translate('Remove this bookmark'),
                    hx_post=DeleteSearchBookmark.url(
                        tab=tab['id'], bookmark=current_bookmark[0]),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML') as control:
                icon('star')
            return control
        with button(
                type='button', cls='vs-icon-button',
                id='search-bookmark-control-' + tab['id'],
                title=translate('Bookmark this filter'),
                aria_label=translate('Bookmark this filter'),
                disabled=(
                    not search_domain
                    or current_draft != tab.get('search', '')) or None,
                hx_get=SearchBookmarkDialog.url(tab=tab['id']),
                hx_target='#modal', hx_swap='innerHTML') as control:
            icon('star' if current_bookmark else 'star-border')
        return control

    def search_pagination(self, tab):
        PageRecords = self.pool.get('cassini.page.records')
        offset = int(tab.get('offset') or 0)
        limit = int(tab.get('limit') or 1000)
        count = int(tab.get('count') or len(tab.get('record_order', [])))
        with nav(
                cls='vs-page-navigation',
                aria_label=translate('Record pages')) as pagination:
            with button(
                    type='button', cls='vs-icon-button',
                    title=translate('Previous page'),
                    aria_label=translate('Previous page'),
                    disabled=offset <= 0 or None,
                    hx_post=PageRecords.url(
                        tab=tab['id'], direction='previous'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML'):
                icon('back')
            span(
                '%d/%d' % (
                    offset // limit + 1 if count else 0,
                    (count + limit - 1) // limit if count else 0),
                cls='vs-page-navigation-position')
            with button(
                    type='button', cls='vs-icon-button',
                    title=translate('Next page'),
                    aria_label=translate('Next page'),
                    disabled=offset + limit >= count or None,
                    hx_post=PageRecords.url(
                        tab=tab['id'], direction='next'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML'):
                icon('forward')
        return pagination

    def search_completion(self, tab):
        with div(
                id='search-completion-' + tab['id'],
                cls='vs-search-completion',
                data_search_completion_list='true',
                role='listbox', hidden=True) as completion:
            for value in self.search_suggestions(tab):
                button(
                    value, type='button',
                    cls='vs-search-completion-option',
                    role='option',
                    data_search_completion_option=value)
        return completion

    def search_selection(self, tab, name, definition):
        selection = definition.get('selection') or []
        if isinstance(selection, str):
            if definition.get('selection_change_with'):
                return None
            Model = self.pool.get(tab['model'])
            method = getattr(Model, selection, None)
            if not method:
                return None
            try:
                selection = method()
            except Exception:
                # A search aid must never prevent the screen from loading.
                return None
        if not isinstance(selection, (list, tuple)):
            return None
        options = []
        for entry in selection:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                return None
            options.append((entry[0], entry[1]))
        return options

    @staticmethod
    def search_filter_control(name, definition, selection, values):
        title = definition.get('string') or name
        type_ = definition.get('type')
        prefix = 'filter__%s__' % name
        with label(cls='vs-filter-field'):
            span(title)
            if type_ == 'boolean':
                with select(
                        name=prefix + 'value',
                        cls='vs-input'):
                    for value, text in (
                            ('', ''),
                            ('true', translate('True')),
                            ('false', translate('False'))):
                        option(
                            text, value=value,
                            selected=(
                                values.get('value') == value) or None)
            elif (
                    type_ in {'selection', 'multiselection'}
                    and selection is not None):
                with select(
                        name=prefix + 'value',
                        cls='vs-input'):
                    option('', value='')
                    for value, text in selection:
                        option(
                            text, value=value,
                            selected=(
                                str(values.get('value')) == str(value))
                            or None)
            elif type_ in {
                    'integer', 'bigint', 'float', 'numeric',
                    'date', 'datetime', 'timestamp', 'time'}:
                input_type = (
                    'number'
                    if type_ in {
                        'integer', 'bigint', 'float', 'numeric'}
                    else 'datetime-local'
                    if type_ in {'datetime', 'timestamp'}
                    else type_)
                with div(cls='vs-filter-range'):
                    input_(
                        type=input_type,
                        name=prefix + 'from',
                        value=values.get('from', ''),
                        placeholder=translate('From'),
                        step='any' if input_type == 'number' else None,
                        cls='vs-input')
                    span('..', aria_hidden='true')
                    input_(
                        type=input_type,
                        name=prefix + 'to',
                        value=values.get('to', ''),
                        placeholder=translate('To'),
                        step='any' if input_type == 'number' else None,
                        cls='vs-input')
            else:
                input_(
                    type='text', name=prefix + 'value',
                    value=values.get('value', ''),
                    placeholder=title, cls='vs-input')

    def search_suggestions(self, tab):
        view = decode_value(tab.get('view', {}))
        query = (
            tab.get('search_draft', tab.get('search', '')) or ''
        )
        parser = search_domain_parser(tab, view)
        return list(dict.fromkeys(
            list(parser.completion(query))
            + list(parser.completion(''))))

    def tree(self, tab, view):
        root = parse_architecture(view)
        relation_origin = tab.get('relation_origin')
        # Relation record dialogs keep their parent origin too, but only an
        # embedded x2many tree has an HTMX target in that origin.  Treating a
        # dialog as an embedded tree used to crash while rendering its search
        # result because ``target`` is intentionally absent there.
        if relation_origin and not relation_origin.get('target'):
            relation_origin = None
        relation_search_origin = tab.get('relation_search_origin')
        embedded = relation_origin or relation_search_origin
        tree_target = (
            relation_origin['target'] if relation_origin
            else relation_search_origin['target']
            if relation_search_origin else '#screen-' + tab['id'])
        editable = (
            not relation_search_origin
            and root.attrib.get('editable') in {'top', 'bottom', '1'}
            and tab.get('access', {}).get('write', True)
            and (
                not relation_origin
                or relation_origin.get('editable', True))
            and not decode_value(
                tab.get('context', {})).get('_datetime'))
        tree_context = dict(Transaction().context)
        tree_context.update(decode_value(tab.get('context', {})))
        tree_context['context'] = dict(tree_context)

        def visible_in_tree(node):
            return not bool(evaluate(
                    node.attrib.get('tree_invisible'), tree_context, False))

        all_buttons = [
            node for node in root
            if node.tag == 'button' and visible_in_tree(node)
            ]
        multiple_buttons = [
            node for node in all_buttons
            if str(node.attrib.get('multiple', '0')).lower() in {
                '1', 'true', 'yes'}
            ]
        all_columns = [
            node for node in root
            if node.tag in {'field', 'button'}
            and node not in multiple_buttons
            and visible_in_tree(node)
            ]
        visibility = tab.get('column_visibility', {})
        columns = []
        for node in all_columns:
            if node.tag != 'field':
                columns.append(node)
                continue
            name = node.attrib['name']
            optional = str(node.attrib.get('optional', '0')).lower() in {
                '1', 'true', 'yes'}
            visible = visibility.get(name, not optional)
            if visible:
                columns.append(node)
        SelectRecord = self.pool.get('cassini.select.record')
        SelectAll = self.pool.get('cassini.select.all.records')
        SortRecords = self.pool.get('cassini.sort.records')
        ToggleColumn = self.pool.get('cassini.toggle.column')
        ToggleTreeNode = self.pool.get('cassini.toggle.tree.node')
        MoveTreeRecord = self.pool.get(
            'cassini.move.tree.record')
        ResizeTreeColumns = self.pool.get(
            'cassini.resize.tree.columns')
        if relation_origin:
            X2ManyAction = self.pool.get('cassini.x2many.action')
            OpenRelationRecord = self.pool.get(
                'cassini.open.relation.record')
        sequence_field = root.attrib.get('sequence')
        select_column_class = (
            'vs-select-column vs-sequence-column'
            if sequence_field and editable else 'vs-select-column')
        rows = self.tree_rows(tab, view)
        first_field = next((
                node.attrib['name']
                for node in columns if node.tag == 'field'), None)
        with div(
                cls='vs-table-wrap',
                data_editable_tree='true' if editable else None) \
                as wrapper:
            if editable and relation_origin:
                button(
                    '', type='button', hidden=True,
                    data_editable_tree_new='true',
                    hx_post=X2ManyAction.url(
                        tab=tab['id'],
                        record=relation_origin['record'],
                        field=relation_origin['field'],
                        action='new'),
                    hx_target=tree_target,
                    hx_swap='outerHTML')
            optional_columns = [
                node for node in all_columns
                if node.tag == 'field' and node.attrib.get('optional')]
            occurrences = {}
            column_occurrences = {}
            for node in all_columns:
                if node.tag != 'field':
                    continue
                name = node.attrib['name']
                occurrences[name] = occurrences.get(name, 0) + 1
                column_occurrences[id(node)] = occurrences[name]
            stored_widths = {}
            if tab.get('screen_width'):
                ViewTreeWidth = self.pool.get('ir.ui.view_tree_width')
                stored_widths = ViewTreeWidth.get_width(
                    tab['model'], int(tab['screen_width']))
            with table(
                    cls='vs-table vs-resizable-table%s%s' % (
                        ' vs-x2many-table' if relation_origin else '',
                        ' vs-relation-search-table'
                        if relation_search_origin else ''),
                data_column_model=tab['model'],
                data_column_resize_url=ResizeTreeColumns.url()):
                with colgroup():
                    col(cls=select_column_class)
                    for node in columns:
                        if node.tag == 'field':
                            name = node.attrib['name']
                            occurrence = column_occurrences[id(node)]
                            field_widths = stored_widths.get(name, [])
                            width = (
                                field_widths[occurrence - 1]
                                if occurrence <= len(field_widths)
                                and field_widths[occurrence - 1]
                                else node.attrib.get('width'))
                            col(
                                style=(
                                    'width:%spx' % width
                                    if str(width).isdigit() else None),
                                data_column_field=name,
                                data_column_occurrence=occurrence)
                        else:
                            col()
                with thead():
                    with tr():
                        with th(cls=select_column_class):
                            with div(cls='vs-tree-header-controls'):
                                with details(
                                        cls='vs-popup vs-column-popup'):
                                    with summary(
                                            cls='vs-tree-menu',
                                            title=translate('Columns'),
                                            aria_label=translate('Columns')):
                                        icon('menu')
                                    with div(
                                            cls='vs-popup-menu',
                                            role='menu',
                                            aria_label=translate('Optional columns')):
                                        if optional_columns:
                                            for node in optional_columns:
                                                name = node.attrib['name']
                                                definition = view.get(
                                                    'fields', {}).get(
                                                        name, {})
                                                default_visible = not (
                                                    str(node.attrib.get(
                                                            'optional', '0'))
                                                    .lower()
                                                    in {
                                                        '1', 'true', 'yes'})
                                                visible = visibility.get(
                                                    name, default_visible)
                                                with label(
                                                        cls=(
                                                            'vs-column-'
                                                            'option')):
                                                    input_(
                                                        type='checkbox',
                                                        name='visible',
                                                        value='true',
                                                        checked=(
                                                            visible or None),
                                                        hx_post=(
                                                            X2ManyAction.url(
                                                                tab=tab['id'],
                                                                record=(
                                                                    relation_origin[
                                                                        'record']),
                                                                field=(
                                                                    relation_origin[
                                                                        'field']),
                                                                action='column')
                                                            if relation_origin
                                                            else None
                                                            if relation_search_origin
                                                            else ToggleColumn.url(
                                                                tab=tab['id'],
                                                                field=name)),
                                                        hx_get=(
                                                            relation_search_origin[
                                                                'url']
                                                            if relation_search_origin
                                                            else None),
                                                        hx_vals=(
                                                            '{"item":"%s"}'
                                                            % name
                                                            if relation_origin
                                                            else '{"column":"%s"}'
                                                            % name
                                                            if relation_search_origin
                                                            else None),
                                                        hx_trigger='change',
                                                        hx_target=tree_target,
                                                        hx_swap='outerHTML',
                                                        hx_include='this')
                                                    span(
                                                        node.attrib.get(
                                                            'string')
                                                        or definition.get(
                                                            'string')
                                                        or name)
                                        else:
                                            span(
                                                translate('No optional columns'),
                                                cls='vs-popup-empty')
                                if not embedded:
                                    input_(
                                        type='checkbox', name='selected',
                                        value='true',
                                        checked=bool(tab.get('record_order'))
                                        and len(tab.get('selected', []))
                                        == len(tab.get('record_order', []))
                                        or None,
                                        aria_label=translate(
                                            'Select all records'),
                                        hx_post=SelectAll.url(tab=tab['id']),
                                        hx_trigger='change',
                                        hx_target=tree_target,
                                        hx_swap='outerHTML',
                                        hx_include='this')
                        for node in columns:
                            if node.tag == 'field':
                                definition = view.get('fields', {}).get(
                                    node.attrib['name'], {})
                                with th():
                                    if embedded:
                                        span(
                                            node.attrib.get('string')
                                            or definition.get('string')
                                            or node.attrib['name'],
                                            cls='vs-sort-button')
                                    else:
                                        button(
                                        node.attrib.get('string')
                                        or definition.get('string')
                                        or node.attrib['name'],
                                        type='button',
                                        cls='vs-sort-button',
                                        hx_post=SortRecords.url(
                                            tab=tab['id'],
                                            field=node.attrib['name']),
                                        hx_target=tree_target,
                                        hx_swap='outerHTML')
                                    span(
                                        '', cls='vs-column-resizer',
                                        role='separator',
                                        tabindex='0',
                                        aria_label=translate(
                                            'Resize %(column)s column',
                                            column=(
                                                node.attrib.get('string')
                                                or definition.get('string')
                                                or node.attrib['name'])),
                                        aria_orientation='vertical',
                                        data_column_resizer='true')
                            else:
                                th(node.attrib.get(
                                    'string', translate('Action')))
                with tbody():
                    for key, depth, has_children in rows:
                        record = tab['records'][key]
                        is_expanded = key in tab.get('expanded', [])
                        renderer = WidgetRenderer(
                            tab, record, view,
                            editable=(
                                editable and not record.get('deleted')),
                            endpoint=(
                                'x2many'
                                if relation_origin else 'record'))
                        row_visual = renderer.evaluate(
                            root.attrib.get('visual'))
                        row_visual = (
                            row_visual
                            if row_visual in {
                                'muted', 'success', 'warning', 'danger'}
                            else None)
                        with tr(
                                cls='vs-row%s%s%s%s%s%s%s' % (
                                    ' vs-row-current'
                                    if key == tab.get('current_record') else '',
                                    ' vs-row-dirty'
                                    if record.get('dirty') else '',
                                    ' vs-visual-' + row_visual
                                    if row_visual else '',
                                    ' vs-x2many-row'
                                    if relation_origin else '',
                                    ' vs-x2many-row-current'
                                    if relation_origin
                                    and key == tab.get('current_record')
                                    else '',
                                    ' vs-x2many-row-deleted'
                                    if record.get('deleted') else '',
                                    ' vs-relation-search-row'
                                    if relation_search_origin else '',
                                    ),
                                data_record=key,
                                data_x2many_record=(
                                    key if relation_origin else None),
                                data_relation_search_row=(
                                    'true'
                                    if relation_search_origin else None)):
                            with td(cls=select_column_class):
                                if relation_search_origin:
                                    input_(
                                        type=(
                                            'checkbox'
                                            if relation_search_origin[
                                                'multiple'] else 'radio'),
                                        name='value', value=record['id'],
                                        aria_label=translate(
                                            'Select %(record)s',
                                            record=(
                                                decode_value(record.get(
                                                        'values', {})).get(
                                                            'rec_name')
                                                or record['id'])))
                                elif relation_origin:
                                    input_(
                                        type='checkbox', name='selected',
                                        value='true',
                                        checked=(
                                            key == tab.get('current_record'))
                                        or None,
                                        aria_label=translate('Select record'),
                                        hx_post=X2ManyAction.url(
                                            tab=tab['id'],
                                            record=relation_origin['record'],
                                            field=relation_origin['field'],
                                            action='select'),
                                        hx_vals='{"item":"%s"}' % key,
                                        hx_trigger='change',
                                        hx_target=tree_target,
                                        hx_swap='outerHTML')
                                else:
                                    input_(
                                        type='checkbox', name='selected',
                                        value='true',
                                        checked=key in tab.get('selected', [])
                                        or None,
                                        aria_label=translate('Select record'),
                                        hx_post=SelectRecord.url(
                                            tab=tab['id'], record=key),
                                        hx_trigger='change',
                                        hx_target=tree_target,
                                        hx_swap='outerHTML',
                                        hx_include='this')
                                if not relation_search_origin:
                                    button(
                                        '', type='button',
                                        cls='vs-row-action',
                                        tabindex='-1',
                                        aria_hidden='true',
                                        data_row_select_action='true',
                                        hx_post=(
                                            X2ManyAction.url(
                                                tab=tab['id'],
                                                record=(
                                                    relation_origin['record']),
                                                field=(
                                                    relation_origin['field']),
                                                action='select')
                                            if relation_origin else
                                            SelectRecord.url(
                                                tab=tab['id'], record=key,
                                                row='true')),
                                        hx_vals=(
                                            '{"item":"%s"}' % key
                                            if relation_origin else None),
                                        hx_target=(
                                            tree_target
                                            if relation_origin else
                                            '#toolbar-' + tab['id']),
                                        hx_swap=(
                                            'none' if relation_origin
                                            else 'outerHTML'))
                                    if not relation_origin or record.get('id'):
                                        button(
                                            '', type='button',
                                            cls='vs-row-action',
                                            tabindex='-1',
                                            aria_hidden='true',
                                            data_row_open_action='true',
                                            hx_post=(
                                                OpenRelationRecord.url(
                                                    tab=tab['id'],
                                                    model=tab['model'],
                                                    record=record.get('id'),
                                                    source_record=(
                                                        relation_origin[
                                                            'record']),
                                                    field=(
                                                        relation_origin[
                                                            'field']))
                                                if relation_origin else
                                                SelectRecord.url(
                                                    tab=tab['id'], record=key,
                                                    row='true', open='true')),
                                            hx_target=(
                                                '#workspace'
                                                if relation_origin else
                                                tree_target),
                                            hx_swap='outerHTML')
                                if sequence_field and editable:
                                    with div(cls='vs-sequence-controls'):
                                        for direction, image in (
                                                ('up', 'arrow-up'),
                                                ('down', 'arrow-down')):
                                            with button(
                                                    type='button',
                                                    cls='vs-tree-toggle',
                                                    title=(
                                                        'Move ' + direction),
                                                    aria_label=(
                                                        'Move ' + direction),
                                                    hx_post=(
                                                        X2ManyAction.url(
                                                            tab=tab['id'],
                                                            record=(
                                                                relation_origin[
                                                                    'record']),
                                                            field=(
                                                                relation_origin[
                                                                    'field']),
                                                            action=(
                                                                'move-'
                                                                + direction))
                                                        if relation_origin
                                                        else MoveTreeRecord.url(
                                                            tab=tab['id'],
                                                            record=key,
                                                            direction=(
                                                                direction))),
                                                    hx_vals=(
                                                        '{"item":"%s"}' % key
                                                        if relation_origin
                                                        else None),
                                                    hx_target=(
                                                        tree_target),
                                                    hx_swap='outerHTML'):
                                                icon(image)
                            for node in columns:
                                cell_visual = renderer.evaluate(
                                    node.attrib.get('visual'))
                                cell_visual = (
                                    cell_visual
                                    if cell_visual in {
                                        'muted', 'success',
                                        'warning', 'danger'}
                                    else None)
                                with td(cls=(
                                        'vs-visual-' + cell_visual
                                        if cell_visual else None)):
                                    if node.tag == 'field':
                                        name = node.attrib['name']
                                        with div(
                                                cls=(
                                                    'vs-tree-cell '
                                                    'vs-hierarchy-cell')):
                                            toggle = None
                                            if (name == first_field
                                                    and has_children):
                                                toggle = button(
                                                    type='button',
                                                    cls=(
                                                        'vs-hierarchy-toggle '
                                                        'vs-tree-toggle'),
                                                    aria_label=(
                                                        translate(
                                                            'Collapse node')
                                                        if is_expanded else
                                                        translate(
                                                            'Expand node')),
                                                    aria_expanded=str(
                                                        is_expanded).lower(),
                                                    hx_post=(
                                                        X2ManyAction.url(
                                                            tab=tab['id'],
                                                            record=(
                                                                relation_origin[
                                                                    'record']),
                                                            field=(
                                                                relation_origin[
                                                                    'field']),
                                                            action='toggle')
                                                        if relation_origin
                                                        else None
                                                        if relation_search_origin
                                                        else ToggleTreeNode.url(
                                                            tab=tab['id'],
                                                            record=key)),
                                                    hx_get=(
                                                        relation_search_origin[
                                                            'url']
                                                        if relation_search_origin
                                                        else None),
                                                    hx_vals=(
                                                        '{"item":"%s"}' % key
                                                        if embedded
                                                        else None),
                                                    hx_target=tree_target,
                                                    hx_swap='outerHTML')
                                                toggle.add(icon(
                                                        'arrow-down'
                                                        if is_expanded else
                                                        'arrow-right'))
                                            with div(
                                                    cls=(
                                                        'vs-tree-content')) \
                                                    as content:
                                                definition = view.get(
                                                    'fields', {}).get(
                                                        name, {})
                                                widget = (
                                                    node.attrib.get('widget')
                                                    or definition.get(
                                                        'type', 'char'))
                                                if widget in {
                                                        'callto', 'email',
                                                        'sip', 'url'}:
                                                    affix = (
                                                        renderer.tree_affix(
                                                            node.attrib,
                                                            protocol=widget))
                                                    if affix is not None:
                                                        content.add(affix)
                                                if node.attrib.get('icon'):
                                                    affix = (
                                                        renderer.tree_affix(
                                                            node.attrib))
                                                    if affix is not None:
                                                        content.add(affix)
                                                for affix in node:
                                                    if affix.tag == 'prefix':
                                                        affix_attributes = dict(
                                                            affix.attrib)
                                                        affix_attributes \
                                                            .setdefault(
                                                                'name', name)
                                                        tag = (
                                                            renderer
                                                            .tree_affix(
                                                                affix_attributes))
                                                        if tag is not None:
                                                            content.add(tag)
                                                if widget == 'url':
                                                    pass
                                                elif editable:
                                                    renderer.render(
                                                        name, node.attrib,
                                                        compact=True)
                                                else:
                                                    renderer.display(
                                                        name, node.attrib)
                                                for affix in node:
                                                    if affix.tag == 'suffix':
                                                        affix_attributes = dict(
                                                            affix.attrib)
                                                        affix_attributes \
                                                            .setdefault(
                                                                'name', name)
                                                        tag = (
                                                            renderer
                                                            .tree_affix(
                                                                affix_attributes))
                                                        if tag is not None:
                                                            content.add(tag)
                                            cell_depth = (
                                                depth
                                                if name == first_field else 0)
                                            HierarchyWidget.row(
                                                content, toggle, cell_depth,
                                                is_expanded,
                                                extra_class=(
                                                    'vs-tree-hierarchy'))
                                    elif not embedded:
                                        attributes = dict(node.attrib)
                                        readonly, _, invisible = (
                                            renderer.states({}, attributes))
                                        if not invisible:
                                            attributes['_state_readonly'] = (
                                                readonly)
                                            self.record_button(
                                                tab, record, attributes,
                                                renderer)
                if any(
                        node.tag == 'field'
                        and str(node.attrib.get('sum', '0')).lower()
                        in {'1', 'true', 'yes'}
                        for node in columns):
                    with tfoot():
                        with tr():
                            td(translate('Total'), cls='vs-select-column')
                            for node in columns:
                                if node.tag != 'field':
                                    td()
                                    continue
                                if str(node.attrib.get(
                                        'sum', '0')).lower() not in {
                                            '1', 'true', 'yes'}:
                                    td()
                                    continue
                                total = sum(
                                    decode_value(tab['records'][key].get(
                                            'values', {})).get(
                                                node.attrib['name']) or 0
                                    for key in tab.get('record_order', []))
                                td(stringify(total), cls='vs-tree-total')
            if not tab.get('record_order'):
                p(
                    tab.get('empty_message') or translate('No records'),
                    cls='vs-empty')
            selected = [
                key for key in tab.get('selected', [])
                if key in tab.get('records', {})]
            if selected and multiple_buttons and not embedded:
                with div(
                        cls='vs-tree-multiple-actions',
                        role='toolbar',
                        aria_label=translate('Selected record actions')):
                    for node in multiple_buttons:
                        attributes = dict(node.attrib)
                        invisible = False
                        readonly = False
                        for key in selected:
                            selected_record = tab['records'][key]
                            selected_renderer = WidgetRenderer(
                                tab, selected_record, view,
                                editable=editable)
                            state_readonly, _, state_invisible = (
                                selected_renderer.states(
                                    {}, attributes))
                            readonly = readonly or state_readonly
                            invisible = invisible or state_invisible
                        if invisible:
                            continue
                        attributes['_state_readonly'] = readonly
                        attributes['_class'] = (
                            'vs-button vs-button-primary '
                            'vs-tree-multiple-button')
                        self.record_button(
                            tab, tab['records'][selected[0]],
                            attributes, selected_renderer)
        return wrapper

    def tree_rows(self, tab, view):
        child_field = view.get('field_childs')
        order = tab.get('record_order', [])
        if not child_field:
            return [(key, 0, False) for key in order]
        children = {}
        child_keys = set()
        positions = {
            key: index for index, key in enumerate(order)}
        for key in order:
            values = decode_value(
                tab['records'][key].get('values', {}))
            keys = sorted([
                str(record_id)
                for record_id in values.get(child_field, [])
                if str(record_id) in tab['records']
                ], key=lambda child: positions.get(child, len(order)))
            children[key] = keys
            child_keys.update(keys)
        roots = [key for key in order if key not in child_keys]
        if not roots:
            roots = list(order)
        expanded = set(tab.get('expanded', []))
        rows = []
        visited = set()

        def add(key, depth):
            if key in visited:
                return
            visited.add(key)
            child_records = children.get(key, [])
            rows.append((key, depth, bool(child_records)))
            if key in expanded:
                for child in child_records:
                    add(child, depth + 1)

        for key in roots:
            add(key, 0)
        return rows

    @staticmethod
    def form_columns(node, columns):
        """Return Sao's effective column count, including unlimited rows."""
        try:
            columns = int(columns)
        except (TypeError, ValueError):
            return 4
        if columns > 0:
            return columns
        row_columns = 0
        maximum = 0
        for child in node:
            if child.tag == 'newline':
                maximum = max(maximum, row_columns)
                row_columns = 0
                continue
            try:
                colspan = max(1, int(child.attrib.get(
                            'colspan',
                            4 if child.tag in {
                                'notebook', 'hpaned', 'vpaned'} else 1)))
            except (TypeError, ValueError):
                colspan = 1
            row_columns += colspan
        return max(1, maximum, row_columns)

    @staticmethod
    def form_layout_style(attributes, columns):
        """Translate Tryton's grid/alignment attributes to CSS grid rules."""
        rules = []
        grid_column = attributes.get('_grid_column')
        grid_row = attributes.get('_grid_row')
        try:
            rowspan = max(1, int(attributes.get('rowspan', 1)))
        except (TypeError, ValueError):
            rowspan = 1
        if grid_column:
            rules.append('grid-column:%s' % grid_column)
        else:
            try:
                colspan = max(1, int(attributes.get('colspan', 1)))
                rules.append(
                    'grid-column: span %d' % min(columns, colspan))
            except (TypeError, ValueError):
                pass
        if grid_row:
            try:
                row = int(str(grid_row).split('/', 1)[0])
                rules.append(
                    'grid-row:%d / %d' % (row, row + rowspan))
            except (TypeError, ValueError):
                rules.append('grid-row:%s' % grid_row)
        elif rowspan > 1:
            rules.append('grid-row: span %d' % rowspan)
        if str(attributes.get('width', '')).isdigit():
            rules.append('min-width: %spx' % attributes['width'])
        if str(attributes.get('height', '')).isdigit():
            rules.append('min-height: %spx' % attributes['height'])
        xexpand = str(attributes.get('xexpand', '1')).lower() not in {
            '0', 'false', 'no'}
        xfill = str(attributes.get('xfill', '1')).lower() not in {
            '0', 'false', 'no'}
        if xexpand and xfill:
            rules.append('width:100%')
        elif not xexpand:
            rules.extend(['min-width:0', 'min-inline-size:0'])
        if 'xalign' in attributes:
            try:
                xalign = float(attributes.get('xalign', 0))
            except (TypeError, ValueError):
                xalign = 0
            alignment = (
                'end' if xalign >= .75
                else 'center' if xalign >= .25
                else 'start')
            rules.extend([
                    'justify-self:%s' % alignment,
                    'text-align:%s' % alignment,
                    ])
        if 'yalign' in attributes:
            try:
                yalign = float(attributes.get('yalign', .5))
            except (TypeError, ValueError):
                yalign = .5
            rules.append(
                'align-self: %s' % (
                    'end' if yalign >= .75
                    else 'center' if yalign >= .25
                    else 'start'))
        return ';'.join(rules) or None

    @staticmethod
    def form_grid_style(node, columns):
        """Build the flexible/min-content column tracks used by Sao forms."""
        columns = ViewRenderer.form_columns(node, columns)
        expanded = set()
        expanded_spans = []
        column = 0
        for child in node:
            if child.tag == 'newline':
                column = 0
                continue
            attributes = child.attrib
            try:
                colspan = max(1, int(attributes.get(
                            'colspan',
                            4 if child.tag in {
                                'notebook', 'hpaned', 'vpaned'} else 1)))
            except (TypeError, ValueError):
                colspan = 1
            colspan = min(columns, colspan)
            if column + colspan > columns:
                column = 0
            default_expand = '0' if child.tag == 'label' else '1'
            xexpand = str(attributes.get(
                    'xexpand', default_expand)).lower() not in {
                        '0', 'false', 'no'}
            span_columns = list(range(column, column + colspan))
            if xexpand:
                if colspan == 1:
                    expanded.add(column)
                else:
                    expanded_spans.append(span_columns)
            column += colspan
        for span_columns in expanded_spans:
            if not expanded.intersection(span_columns):
                expanded.add(span_columns[(len(span_columns) - 1) // 2])
        tracks = [
            'minmax(0, 1fr)'
            if column in expanded else 'min-content'
            for column in range(columns)
            ]
        return 'grid-template-columns:%s' % ' '.join(tracks)

    def form(self, tab, view):
        key = tab.get('current_record')
        if not key or key not in tab.get('records', {}):
            return p(translate('No record selected'), cls='vs-empty')
        record = tab['records'][key]
        access = tab.get('access', {})
        editable = (
            access.get('create', True) if record.get('new')
            else access.get('write', True))
        editable = editable and not decode_value(
            tab.get('context', {})).get('_datetime')
        renderer = WidgetRenderer(tab, record, view, editable=editable)
        root = parse_architecture(view)
        cursor = root.attrib.get('cursor')
        focus_nodes = list(root.iter('field'))
        if cursor:
            focus_nodes.sort(
                key=lambda node: node.attrib.get('name') != cursor)
        for node in focus_nodes:
            definition = view.get(
                'fields', {}).get(node.attrib.get('name'), {})
            readonly, _, invisible = renderer.states(
                definition, dict(node.attrib))
            if not readonly and not invisible and editable:
                node.attrib['autofocus'] = '1'
                break
        with div(
                cls='vs-form',
                data_form_cursor=cursor,
                style=self.form_grid_style(
                    root, root.attrib.get('col', 4))) as tag:
            if root.attrib.get('scan_code'):
                ScanCode = self.pool.get('cassini.scan.code')
                scan_states = {
                    'states': root.attrib.get('scan_code_states')}
                scan_readonly, _, scan_invisible = renderer.states(
                    {}, scan_states)
                with form(
                        cls='vs-scan-code%s' % (
                            ' vs-hidden' if scan_invisible else ''),
                        style='grid-column:1/-1;grid-row:1'):
                    input_(
                        type='text', name='code',
                        placeholder=translate('Scan or enter a code'),
                        aria_label=translate('Code'), cls='vs-input',
                        autocomplete='off')
                    with button(
                            type='button',
                            cls='vs-icon-button vs-button-primary',
                            disabled=scan_readonly or None,
                            title=translate('Scan'), aria_label=translate('Scan'),
                            hx_post=ScanCode.url(
                                tab=tab['id'], record=record['key']),
                            hx_include='closest form',
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon('barcode-scanner')
            self.form_children(
                tag, root, renderer, tab, record,
                columns=root.attrib.get('col', 4),
                row_start=2 if root.attrib.get('scan_code') else 1)
        return tag

    def form_children(
            self, parent, node, renderer, tab, record, path=(),
            inherited_readonly=False, columns=4, row_start=1):
        columns = self.form_columns(node, columns)
        mnemonics = {}
        for item in node:
            if item.tag != 'label' or not item.attrib.get('name'):
                continue
            definition = renderer.view.get(
                'fields', {}).get(item.attrib['name'], {})
            text = (
                item.attrib.get('string')
                or definition.get('string')
                or item.attrib['name'])
            mnemonics[item.attrib['name']] = form_accesskey(text)
        grid_column = 1
        grid_row = row_start
        for index, child in enumerate(node):
            attributes = dict(child.attrib)
            child_path = path + (index,)
            if child.tag == 'label':
                attributes.setdefault('xexpand', '0')
                attributes.setdefault('xalign', '1.0')
                attributes.setdefault('yalign', '0.5')
            if child.tag in {'notebook', 'hpaned', 'vpaned'}:
                attributes.setdefault('colspan', '4')
            if child.tag == 'newline':
                grid_column = 1
                grid_row += 1
                continue
            try:
                colspan = max(1, int(attributes.get('colspan', 1)))
            except (TypeError, ValueError):
                colspan = 1
            colspan = min(columns, colspan)
            if grid_column + colspan > columns + 1:
                grid_column = 1
                grid_row += 1
            attributes['_grid_column'] = '%d / %d' % (
                grid_column, grid_column + colspan)
            attributes['_grid_row'] = '%d / %d' % (
                grid_row, grid_row + 1)
            grid_column += colspan
            if (
                    tab.get('exclude_field')
                    and attributes.get('name') == tab['exclude_field']
                    and child.tag in {
                        'field', 'label', 'separator', 'page', 'group'}):
                continue
            layout_style = self.form_layout_style(attributes, columns)
            state_readonly = inherited_readonly
            if child.tag != 'field':
                definition = renderer.view.get(
                    'fields', {}).get(attributes.get('name'), {})
                readonly, _, invisible = renderer.states(
                    definition, attributes)
                if invisible:
                    continue
                state_readonly = state_readonly or readonly
            if child.tag == 'field':
                if inherited_readonly:
                    attributes['readonly'] = '1'
                attributes['_accesskey'] = mnemonics.get(
                    attributes['name'])
                attributes['_columns'] = columns
                attributes['_layout_style'] = layout_style
                parent.add(renderer.render(attributes['name'], attributes))
            elif child.tag == 'label':
                name = attributes.get('name')
                definition = renderer.view.get('fields', {}).get(name, {})
                _, required, _ = renderer.states(
                    definition, attributes)
                parent.add(label(
                    attributes.get('string')
                    or definition.get('string')
                    or name or '',
                    html_for=(
                        dom_id(
                            'field', renderer.tab['id'],
                            renderer.record['key'], name) + '-input'
                        if name else None),
                    cls='vs-standalone-label%s' % (
                        ' vs-label-required' if required else ''),
                    data_accesskey=form_accesskey(
                        attributes.get('string')
                        or definition.get('string')
                        or name),
                    title=attributes.get('help'),
                    style=layout_style))
            elif child.tag == 'button':
                attributes['_state_readonly'] = state_readonly
                attributes['_layout_style'] = layout_style
                parent.add(self.record_button(
                        tab, record, attributes, renderer))
            elif child.tag == 'link':
                if record.get('id'):
                    control = self.form_link(
                        tab, record, renderer, attributes, layout_style)
                    if control is not None:
                        parent.add(control)
            elif child.tag == 'image':
                name = attributes.get('name')
                value = renderer.values.get(name, name)
                image_class = (
                    'vs-form-image vs-image-'
                    + attributes.get('border', 'square'))
                if attributes.get('type') == 'url' and value:
                    parent.add(img(
                            src=value,
                            width=attributes.get('size', 48),
                            height=attributes.get('size', 48),
                            alt=attributes.get('string', ''),
                            cls=image_class,
                            title=attributes.get('help'),
                            style=layout_style))
                elif attributes.get('type') == 'color':
                    color = css_color(value)
                    parent.add(div(
                            cls=image_class + ' vs-form-color',
                            style='%s;%s' % (
                                layout_style or '',
                                'background-color: %s' % color
                                if color else ''),
                            title=attributes.get('help'),
                            aria_label=attributes.get('string', '')))
                elif value:
                    with span(
                            cls=image_class,
                            title=(
                                attributes.get('help')
                                or attributes.get('string', '')),
                            style=layout_style) as image:
                        icon(str(value).removeprefix('tryton-'))
                    parent.add(image)
            elif child.tag == 'group':
                group_columns = attributes.get('col', 4)
                expandable = str(
                    attributes.get('expandable', '0')).lower() in {
                        '1', 'true', 'yes'}
                if expandable:
                    with details(
                            cls='vs-group vs-expandable',
                            style=layout_style, open=True) as group:
                        summary(
                            attributes.get('string')
                            or translate('Details'),
                            cls='vs-expandable-summary')
                        with div(
                                cls='vs-group-body',
                                style=self.form_grid_style(
                                    child, group_columns)) as body:
                            self.form_children(
                                body, child, renderer, tab, record,
                                child_path, state_readonly, group_columns)
                else:
                    group_style = ';'.join(filter(None, (
                                layout_style,
                                self.form_grid_style(
                                    child, group_columns))))
                    with fieldset(
                            cls='vs-group', style=group_style) as group:
                        if attributes.get('string'):
                            legend(attributes['string'])
                        self.form_children(
                            group, child, renderer, tab, record, child_path,
                            state_readonly, group_columns)
                parent.add(group)
            elif child.tag == 'notebook':
                notebook_id = 'n-' + '-'.join(map(str, child_path))
                pages = [
                    page for page in child
                    if page.tag == 'page'
                    and (
                        not tab.get('exclude_field')
                        or page.attrib.get('name') != tab['exclude_field'])
                    and not renderer.states({}, dict(page.attrib))[2]
                    ]
                active = int(tab.get('pages', {}).get(notebook_id, 0))
                active = min(active, max(0, len(pages) - 1))
                notebook_kind = tab.get('kind')
                stateful_notebook = notebook_kind in {
                    'window', 'wizard', 'preferences'}
                SwitchPage = self.pool.get('cassini.switch.page')
                SwitchPreferencePage = self.pool.get(
                    'cassini.switch.preference.page')
                with section(
                        cls='vs-notebook',
                        style=layout_style) as notebook:
                    if stateful_notebook:
                        with nav(
                                cls=(
                                    'vs-notebook-tabs vs-local-tabs '
                                    'vs-tab-strip'),
                                aria_label=attributes.get(
                                    'string',
                                    translate('Notebook pages'))):
                            with ul(cls='vs-tab-list', role='tablist'):
                                for page_index, page in enumerate(pages):
                                    selected = page_index == active
                                    page_id = dom_id(
                                        'notebook-page', tab['id'],
                                        notebook_id, page_index)
                                    tab_id = dom_id(
                                        'notebook-tab', tab['id'],
                                        notebook_id, page_index)
                                    with li(
                                            role='presentation',
                                            cls='vs-local-tab%s' % (
                                                ' vs-local-tab-active'
                                                if selected else '')):
                                        with button(
                                                type='button',
                                                id=tab_id,
                                                role='tab',
                                                aria_controls=page_id,
                                                aria_selected=str(
                                                    selected).lower(),
                                                cls='vs-local-tab-title',
                                                hx_post=(
                                                    SwitchPreferencePage.url(
                                                        notebook=notebook_id,
                                                        page=page_index)
                                                    if notebook_kind
                                                    == 'preferences'
                                                    else SwitchPage.url(
                                                        tab=tab['id'],
                                                        notebook=notebook_id,
                                                        page=page_index)),
                                                hx_target=(
                                                    'this'
                                                    if notebook_kind
                                                    == 'preferences'
                                                    else '#screen-' + tab['id']
                                                    if notebook_kind
                                                    == 'window'
                                                    else '#wizard-'
                                                    + tab['id']),
                                                hx_swap=(
                                                    'none'
                                                    if notebook_kind
                                                    == 'preferences'
                                                    else 'outerHTML'),
                                                data_preference_notebook_tab=(
                                                    notebook_id
                                                    if notebook_kind
                                                    == 'preferences'
                                                    else None),
                                                data_preference_notebook_page=(
                                                    page_index
                                                    if notebook_kind
                                                    == 'preferences'
                                                    else None)):
                                            if page.attrib.get('icon'):
                                                icon(page.attrib[
                                                        'icon'].removeprefix(
                                                            'tryton-'))
                                            span(
                                                page.attrib.get('string')
                                                or page.attrib.get('name')
                                                or translate(
                                                    'Page %(page)d',
                                                    page=page_index + 1))
                    if pages and notebook_kind in {'window', 'wizard'}:
                        page = pages[active]
                        page_id = dom_id(
                            'notebook-page', tab['id'],
                            notebook_id, active)
                        tab_id = dom_id(
                            'notebook-tab', tab['id'],
                            notebook_id, active)
                        with section(
                                id=page_id,
                                role='tabpanel',
                                aria_labelledby=tab_id,
                                cls='vs-page',
                                style=self.form_grid_style(
                                    page, page.attrib.get(
                                        'col', 4))) as page_container:
                            self.form_children(
                                page_container, page, renderer, tab, record,
                                child_path + (active,), state_readonly,
                                page.attrib.get('col', 4))
                    elif pages and notebook_kind == 'preferences':
                        for page_index, page in enumerate(pages):
                            selected = page_index == active
                            page_id = dom_id(
                                'notebook-page', tab['id'],
                                notebook_id, page_index)
                            tab_id = dom_id(
                                'notebook-tab', tab['id'],
                                notebook_id, page_index)
                            with section(
                                    id=page_id,
                                    role='tabpanel',
                                    aria_labelledby=tab_id,
                                    cls='vs-page',
                                    hidden=None if selected else True,
                                    data_preference_notebook_tab=notebook_id,
                                    data_preference_notebook_page=page_index,
                                    style=self.form_grid_style(
                                        page, page.attrib.get(
                                            'col', 4))) as page_container:
                                self.form_children(
                                    page_container, page, renderer,
                                    tab, record,
                                    child_path + (page_index,),
                                    state_readonly,
                                    page.attrib.get('col', 4))
                    else:
                        for page_index, page in enumerate(pages):
                            with section(
                                    cls='vs-page',
                                    aria_label=page.attrib.get('string'),
                                    style=self.form_grid_style(
                                        page, page.attrib.get(
                                            'col', 4))
                                    ) as page_container:
                                if page.attrib.get('string'):
                                    h3(page.attrib['string'])
                                self.form_children(
                                    page_container, page, renderer,
                                    tab, record,
                                    child_path + (page_index,),
                                    state_readonly,
                                    page.attrib.get('col', 4))
                parent.add(notebook)
            elif child.tag == 'page':
                page_style = ';'.join(filter(None, (
                            layout_style,
                            self.form_grid_style(
                                child, attributes.get('col', 4)))))
                with section(
                        cls='vs-page', style=page_style) as container:
                    if attributes.get('string'):
                        h3(attributes['string'])
                    self.form_children(
                        container, child, renderer, tab, record,
                        child_path, state_readonly,
                        attributes.get('col', 4))
                parent.add(container)
            elif child.tag in {'hpaned', 'vpaned'}:
                with div(
                        cls='vs-paned vs-' + child.tag,
                        style=layout_style,
                        data_position=attributes.get('position')) as paned:
                    self.form_children(
                        paned, child, renderer, tab, record, child_path,
                        state_readonly, columns)
                parent.add(paned)
            elif child.tag == 'separator':
                with div(
                        cls='vs-separator-block',
                        style=layout_style,
                        title=attributes.get('help')) as separator:
                    if attributes.get('string'):
                        div(
                            attributes['string'],
                            cls='vs-separator-label')
                    hr(cls='vs-separator')
                parent.add(separator)
            else:
                container_style = ';'.join(filter(None, (
                            layout_style,
                            self.form_grid_style(child, columns))))
                with div(
                        cls='vs-container vs-' + child.tag,
                        style=container_style) as container:
                    self.form_children(
                        container, child, renderer, tab, record, child_path,
                        state_readonly, columns)
                parent.add(container)

    def form_link(
            self, tab, record, renderer, attributes, layout_style):
        OpenAction = self.pool.get('cassini.open.action')
        action_id = attributes.get('id')
        title = attributes.get('string') or translate('Open')
        counts = []
        domain_titles = []
        try:
            action = self.pool.get('ir.action')(
                int(action_id)).get_action_value()
        except (TypeError, ValueError):
            action = None
        if action:
            title = action.get('name') or title
            context = dict(Transaction().context)
            context.update(renderer.state_context)
            context.update({
                    'active_model': tab['model'],
                    'active_id': record['id'],
                    'active_ids': [record['id']],
                    })
            action_context = evaluate(
                action.get('pyson_context'), context, {}) or {}
            context.update(action_context)
            context['context'] = context
            domain = combine_domains(
                evaluate(action.get('pyson_domain'), context, []) or [],
                evaluate(
                    action.get('pyson_search_value'),
                    context, []) or [])
            try:
                Model = self.pool.get(action.get('res_model'))
            except (KeyError, TypeError):
                Model = None
            for name, tab_domain, count in action.get('domains', []):
                if not count:
                    continue
                domain_titles.append(name)
                if Model:
                    counts.append(Model.search_count(combine_domains(
                                domain,
                                evaluate(tab_domain, context, []) or []),
                            limit=100))
                else:
                    counts.append(0)
            if not domain_titles:
                counts = [
                    Model.search_count(domain, limit=100) if Model else 0]
        if (
                attributes.get('empty') == 'hide'
                and counts and not any(counts)):
            return None
        with button(
                type='button',
                cls='vs-link-button',
                title=attributes.get('help') or title,
                style=layout_style,
                hx_post=OpenAction.url(
                    action=action_id,
                    model=tab['model'],
                    record=record['id'], origin=True),
                hx_target='#workspace',
                hx_swap='outerHTML') as control:
            if attributes.get('icon'):
                icon(attributes['icon'].removeprefix('tryton-'))
            with span(cls='vs-link-label'):
                if domain_titles:
                    span(title, cls='vs-link-title')
                    for name, count in zip(domain_titles, counts):
                        with span(cls='vs-link-domain'):
                            span(name)
                            span(
                                '99+' if count > 99 else str(count),
                                cls='vs-link-count')
                else:
                    with span(cls='vs-link-domain vs-link-title'):
                        span(title)
                        if counts:
                            span(
                                '99+' if counts[0] > 99
                                else str(counts[0]),
                                cls='vs-link-count')
        return control

    def record_button(self, tab, record, attributes, renderer=None):
        RunButton = self.pool.get('cassini.run.button')
        icon_name = attributes.get('icon')
        if renderer:
            state_values = renderer.evaluate(
                attributes.get('states'), {}) or {}
            if isinstance(state_values, dict):
                icon_name = state_values.get('icon', icon_name)
        classes = attributes.get('_class', 'vs-button')
        if 'vs-record-button' not in classes.split():
            classes += ' vs-record-button'
        with button(
                type='button',
                cls=classes,
                title=attributes.get('help'),
                style=attributes.get('_layout_style'),
                disabled=(
                    record.get('new')
                    and attributes.get('type', 'class') != 'instance')
                or attributes.get('_state_readonly') or None,
                hx_confirm=attributes.get('confirm'),
                hx_post=RunButton.url(
                    tab=tab['id'], button=attributes.get('name', ''),
                    kind=attributes.get('type', 'class'),
                    record=record['key']),
                hx_target='#workspace',
                hx_swap='outerHTML') as control:
            if icon_name:
                icon(icon_name.removeprefix('tryton-'))
            span(
                attributes.get('string')
                or attributes.get('name', translate('Action')))
        return control

    def list_form(self, tab, view):
        root = parse_architecture(view)
        with div(cls='vs-list-form') as tag:
            for key in tab.get('record_order', []):
                record = tab['records'][key]
                access = tab.get('access', {})
                editable = (
                    access.get('create', True) if record.get('new')
                    else access.get('write', True))
                editable = editable and not decode_value(
                    tab.get('context', {})).get('_datetime')
                renderer = WidgetRenderer(
                    tab, record, view, editable=editable)
                with article(
                        id=dom_id('card', tab['id'], key),
                        cls='vs-card',
                        style=self.form_grid_style(
                            root, root.attrib.get('col', 4))) as card:
                    self.form_children(
                        card, root, renderer, tab, record,
                        columns=root.attrib.get('col', 4))
                tag.add(card)
            if not tab.get('record_order'):
                p(translate('No records'), cls='vs-empty')
        return tag

    def calendar(self, tab, view):
        root = parse_architecture(view)
        start_name = root.attrib.get('dtstart')
        end_name = root.attrib.get('dtend')
        field_nodes = [
            node for node in root if node.tag == 'field']
        current = date.fromisoformat(
            tab.get('calendar_date') or date.today().isoformat())
        mode = tab.get(
            'calendar_mode', root.attrib.get('mode', 'month'))
        Navigate = self.pool.get('cassini.navigate.calendar')
        SetCalendarMode = self.pool.get(
            'cassini.set.calendar.mode')
        NewCalendarRecord = self.pool.get(
            'cassini.new.calendar.record')
        MoveCalendarRecord = self.pool.get(
            'cassini.move.calendar.record')
        SelectRecord = self.pool.get('cassini.select.record')
        editable = (
            str(root.attrib.get('editable', '1')).lower()
            not in {'0', 'false', 'no'}
            and tab.get('access', {}).get('create', True)
            and not decode_value(
                tab.get('context', {})).get('_datetime'))
        events = []
        for key in tab.get('record_order', []):
            record = tab['records'][key]
            values = decode_value(record.get('values', {}))
            start = values.get(start_name)
            end = values.get(end_name) if end_name else start
            start_date = (
                start.date() if isinstance(start, datetime) else start)
            end_date = end.date() if isinstance(end, datetime) else end
            events.append((
                    key, record, values,
                    start_date, end_date or start_date))
        if mode == 'day':
            days = [current]
        elif mode == 'week':
            first = date.fromordinal(
                current.toordinal() - current.weekday())
            days = [
                date.fromordinal(first.toordinal() + offset)
                for offset in range(7)]
        else:
            weeks = month_calendar.Calendar().monthdatescalendar(
                current.year, current.month)
            days = [day for week in weeks for day in week]
        with div(
                cls='vs-calendar vs-calendar-' + mode,
                style=(
                    'max-width: %spx' % root.attrib['width']
                    if str(root.attrib.get('width', '')).isdigit()
                    else None)) as calendar:
            with header(cls='vs-calendar-header'):
                button(
                    translate('Previous'), type='button', cls='vs-button',
                    hx_post=Navigate.url(
                        tab=tab['id'], direction='previous'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML')
                h2(
                    current.strftime(
                        '%A, %d %B %Y' if mode == 'day'
                        else 'Week of %d %B %Y' if mode == 'week'
                        else '%B %Y'))
                with nav(
                        cls='vs-calendar-modes',
                        aria_label=translate('Calendar mode')):
                    for candidate, title in (
                            ('day', translate('Day')),
                            ('week', translate('Week')),
                            ('month', translate('Month'))):
                        button(
                            title,
                            type='button',
                            cls='vs-button%s' % (
                                ' vs-button-active'
                                if candidate == mode else ''),
                            aria_pressed=str(
                                candidate == mode).lower(),
                            hx_post=SetCalendarMode.url(
                                tab=tab['id'], mode=candidate),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML')
                button(
                    translate('Today'), type='button', cls='vs-button',
                    hx_post=Navigate.url(
                        tab=tab['id'], direction='today'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML')
                button(
                    translate('Next'), type='button', cls='vs-button',
                    hx_post=Navigate.url(
                        tab=tab['id'], direction='next'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML')
            with div(cls='vs-calendar-grid'):
                if mode == 'month':
                    for weekday in month_calendar.day_abbr:
                        div(weekday, cls='vs-calendar-weekday')
                else:
                    for day in days:
                        div(
                            day.strftime('%a %d'),
                            cls='vs-calendar-weekday')
                for day in days:
                    with section(
                            cls='vs-calendar-day%s' % (
                                ' vs-calendar-day-outside'
                                if mode == 'month'
                                and day.month != current.month else ''),
                            aria_label=day.isoformat()):
                        h3(str(day.day))
                        if editable:
                            button(
                                '+', type='button',
                                cls='vs-calendar-new',
                                title=translate('New event'),
                                aria_label=translate(
                                    'New event on %(date)s',
                                    date=day.isoformat()),
                                hx_post=NewCalendarRecord.url(
                                    tab=tab['id'],
                                    day=day.isoformat()),
                                hx_target='#screen-' + tab['id'],
                                hx_swap='outerHTML')
                        for (
                                key, record, values,
                                start_date, end_date) in events:
                            if (start_date and end_date
                                    and start_date <= day <= end_date):
                                foreground = css_color(values.get(
                                    root.attrib.get('color')))
                                background = css_color(values.get(
                                    root.attrib.get('background_color')))
                                style = ';'.join(filter(None, [
                                        'color: %s' % foreground
                                        if foreground else None,
                                        'background-color: %s' % background
                                        if background else None,
                                        ])) or None
                                with article(
                                        cls='vs-calendar-event',
                                        style=style):
                                    if editable:
                                        with div(
                                                cls='vs-calendar-move'):
                                            for direction, image in (
                                                    ('previous', 'back'),
                                                    ('next', 'forward')):
                                                with button(
                                                        type='button',
                                                        cls=(
                                                            'vs-tree-toggle'),
                                                        title=(
                                                            'Move event '
                                                            + direction),
                                                        aria_label=(
                                                            'Move event '
                                                            + direction),
                                                        hx_post=(
                                                            MoveCalendarRecord
                                                            .url(
                                                                tab=tab['id'],
                                                                record=key,
                                                                direction=(
                                                                    direction)
                                                                )),
                                                        hx_target=(
                                                            '#screen-'
                                                            + tab['id']),
                                                        hx_swap='outerHTML'):
                                                    icon(image)
                                    button(
                                        values.get('rec_name') or key,
                                        type='button',
                                        cls='vs-link-button',
                                        hx_post=SelectRecord.url(
                                            tab=tab['id'],
                                            record=key,
                                            open='true'),
                                        hx_target=(
                                            '#screen-' + tab['id']),
                                        hx_swap='outerHTML')
                                    if isinstance(
                                            values.get(start_name),
                                            datetime):
                                        p(
                                            values[start_name].strftime(
                                                '%H:%M'),
                                            cls='vs-calendar-start')
                                    renderer = WidgetRenderer(
                                        tab, record, view,
                                        editable=False)
                                    for node in field_nodes:
                                        name = node.attrib['name']
                                        if name not in {
                                                start_name, end_name}:
                                            with div(
                                                    cls=(
                                                        'vs-calendar-'
                                                        'detail')):
                                                renderer.display(
                                                    name, node.attrib)
            if not events:
                p(translate('No events'), cls='vs-empty')
        return calendar

    def wizard(self, tab):
        WizardStep = self.pool.get('cassini.wizard.step')
        WizardHelp = self.pool.get('cassini.wizard.help')
        view = decode_value(tab.get('view', {}))
        values = decode_value(tab.get('values', {}))
        pseudo_tab = {
            'id': tab['id'],
            'model': view.get('model'),
            'kind': 'wizard',
            'pages': tab.get('pages', {}),
            'screen_width': self.interface.data.get('screen_width'),
            }
        pseudo_record = {
            'key': 'wizard',
            'id': None,
            'values': values,
            'new': True,
            'x2many': tab.setdefault('x2many', {}),
            }
        renderer = WidgetRenderer(
            pseudo_tab, pseudo_record, view,
            editable=True, endpoint='wizard')
        root = parse_architecture(view)
        wizard = form(
            id='wizard-' + tab['id'],
            cls='vs-form vs-wizard%s' % (
                ' vs-wizard-help-open'
                if tab.get('wizard_help_open') else ''),
            hx_sync='body:queue all')
        with header(cls='vs-wizard-header') as wizard_header:
            h2(tab['title'], id='wizard-title-' + tab['id'])
            try:
                self.pool.get('nantic.chat.conversation')
            except KeyError:
                pass
            else:
                with button(
                        type='button',
                        cls='vs-icon-button vs-wizard-help-toggle%s' % (
                            ' vs-button-active'
                            if tab.get('wizard_help_open') else ''),
                        title=translate('Help'),
                        aria_label=translate('Help'),
                        aria_pressed=str(bool(tab.get(
                                    'wizard_help_open'))).lower(),
                        hx_post=WizardHelp.url(
                            tab=tab['id'], action='toggle'),
                        hx_target='#workspace',
                        hx_swap='outerHTML'):
                    icon('question')
        wizard.add(wizard_header)
        if root.tag == 'tree':
            preview_tab = dict(pseudo_tab)
            preview_tab.update({
                    'access': {
                        'create': False,
                        'delete': False,
                        'read': True,
                        'write': False,
                        },
                    'column_visibility': {},
                    'count': 1,
                    'current_record': 'wizard',
                    'expanded': [],
                    'offset': 0,
                    'record_order': ['wizard'],
                    'records': {'wizard': pseudo_record},
                    'selected': [],
                    'view': tab['view'],
                    'view_type': 'tree',
                    })
            content = div(cls='vs-wizard-content')
            content.add(self.tree(preview_tab, view))
        else:
            content = div(
                cls='vs-form vs-wizard-content',
                style=self.form_grid_style(
                    root, root.attrib.get('col', 4)))
            self.form_children(
                content, root, renderer, pseudo_tab, pseudo_record,
                columns=root.attrib.get('col', 4))
        wizard.add(content)
        if tab.get('wizard_help_open'):
            wizard.add(self.wizard_help(tab))
        with div(cls='vs-dialog-actions') as actions:
            for definition in decode_value(tab.get('buttons', [])):
                button(
                    definition['string'], type='button',
                    cls='vs-button%s' % (
                        ' vs-button-primary'
                        if definition.get('default') else ''),
                    data_modal_cancel=(
                        'true'
                        if definition['state'] == tab.get(
                            'wizard_end_state') else None),
                    hx_post=WizardStep.url(
                        tab=tab['id'], state=definition['state']),
                    hx_include='closest form',
                    hx_target='#workspace',
                    hx_swap='outerHTML')
        wizard.add(actions)
        return wizard

    def wizard_help(self, tab):
        WizardHelp = self.pool.get('cassini.wizard.help')
        Notification = self.pool.get('nantic_connection.notification')
        filter_ = tab.get('wizard_help_filter') or 'unread'
        view = decode_value(tab.get('view', {}))
        view_ids = [view['view_id']] if view.get('view_id') else []
        notifications = Notification.get_notifications(
            view_ids, [tab.get('wizard_name')], filter_)
        selected = next((
                notification for notification in notifications
                if str(notification.get('id'))
                == str(tab.get('wizard_help_update'))), None)
        if tab.get('wizard_help_update') and not selected:
            selected = next((
                    notification for notification
                    in Notification.get_notifications(
                        view_ids, [tab.get('wizard_name')], 'all')
                    if str(notification.get('id'))
                    == str(tab.get('wizard_help_update'))), None)
        with aside(
                id='wizard-help-' + tab['id'],
                cls='vs-wizard-help') as panel:
            with header(cls='vs-wizard-help-header'):
                h3(translate('Updates'))
                with div(
                        cls='vs-wizard-help-actions',
                        role='group',
                        aria_label=translate('Updates')):
                    for value, image, title in (
                            ('unread', 'notification',
                                translate('Unread updates')),
                            ('all', 'history',
                                translate('All updates'))):
                        with button(
                                type='button',
                                cls='vs-help-heading-button%s' % (
                                    ' vs-button-active'
                                    if filter_ == value else ''),
                                title=title, aria_label=title,
                                hx_post=WizardHelp.url(
                                    tab=tab['id'], action='filter',
                                    filter=value),
                                hx_target='#workspace',
                                hx_swap='outerHTML'):
                            icon(image)
            if selected:
                with button(
                        translate('Back'), type='button',
                        cls='vs-help-document-back',
                        hx_post=WizardHelp.url(
                            tab=tab['id'], action='back'),
                        hx_target='#workspace', hx_swap='outerHTML'):
                    pass
                content = selected.get('notification_html')
                if isinstance(content, (bytes, bytearray)):
                    content = bytes(content).decode('utf-8')
                elif isinstance(content, list):
                    content = bytes(content).decode('utf-8')
                div(raw(content or ''), cls='vs-help-update-content')
            elif notifications:
                with div(cls='vs-help-update-list'):
                    for notification in notifications:
                        with button(
                                type='button',
                                cls='vs-help-update%s' % (
                                    '' if notification.get('has_read')
                                    else ' vs-help-update-unread'),
                                hx_post=WizardHelp.url(
                                    tab=tab['id'], action='update',
                                    update=notification['id']),
                                hx_target='#workspace',
                                hx_swap='outerHTML'):
                            strong(
                                notification.get('subject')
                                or translate('Update'))
                            span(
                                str(notification.get('datetime') or ''),
                                cls='vs-muted')
            else:
                p(translate('No updates available.'), cls='vs-muted')
        return panel

    def url(self, tab):
        with div(cls='vs-url-tab') as tag:
            h2(tab['title'])
            p(translate('This action opens an external address.'))
            a(
                translate('Open link'), href=tab['url'], target='_blank',
                rel='noreferrer noopener', cls='vs-button vs-button-primary')
        return tag


class WorkspaceRenderer:
    def __init__(self, interface):
        self.interface = interface
        self.pool = Pool()

    @staticmethod
    def wizard_dialog_class(tab):
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(view.get('arch') or '<form/>')
        expanded_widgets = {
            'chart', 'code', 'dict', 'document', 'html',
            'many2many', 'multiselection',
            'one2many', 'richtext', 'text',
            }
        expanded = root.tag != 'form' or tab.get('wizard_help_open')
        if not expanded:
            fields = view.get('fields', {})
            for node in root.iter('field'):
                definition = fields.get(node.attrib.get('name'), {})
                widget = (
                    node.attrib.get('widget')
                    or definition.get('type', 'char'))
                if widget in expanded_widgets:
                    expanded = True
                    break
        return 'vs-modal vs-wizard-dialog%s' % (
            ' vs-wizard-dialog-wide' if expanded else '')

    def render(self, include_tabs=False):
        view_renderer = ViewRenderer(self.interface)
        with div(id='workspace', cls='vs-workspace') as workspace:
            tab = self.interface.active_tab
            modal_wizard = (
                tab if tab
                and tab.get('kind') == 'wizard'
                and not tab.get('window') else None)
            modal_relation = (
                tab if tab and tab.get('relation_modal') else None)
            if modal_wizard:
                tab = self.interface.get_tab(
                    modal_wizard.get('return_tab'))
            elif modal_relation:
                tab = self.interface.get_tab(
                    modal_relation.get('return_tab'))
            with div(
                    id='active-panel',
                    cls='vs-active-panel%s' % (
                        '' if tab else ' vs-active-panel-empty')):
                if not tab:
                    self.welcome()
                elif tab.get('kind') == 'window':
                    view_renderer.screen(tab)
                elif tab.get('kind') == 'wizard':
                    view_renderer.wizard(tab)
                elif tab.get('kind') == 'dashboard':
                    view_renderer.screen(tab)
                elif tab.get('kind') == 'url':
                    view_renderer.url(tab)
                else:
                    p(translate('Unsupported tab type'), cls='vs-notice')
            if modal_wizard:
                with div(
                        cls=(
                            'vs-modal-host '
                            'vs-wizard-modal-host')):
                    with div(cls='vs-modal-backdrop'):
                        with section(
                                role='dialog',
                                aria_modal='true',
                                aria_labelledby=(
                                    'wizard-title-'
                                    + modal_wizard['id']),
                                cls=self.wizard_dialog_class(
                                    modal_wizard)):
                            view_renderer.wizard(modal_wizard)
            elif modal_relation:
                with div(
                        cls=(
                            'vs-modal-host '
                            'vs-relation-record-modal-host')):
                    with div(cls='vs-modal-backdrop'):
                        with section(
                                role='dialog',
                                aria_modal='true',
                                aria_label=modal_relation['title'],
                                cls=(
                                    'vs-modal '
                                    'vs-relation-record-dialog')):
                            view_renderer.screen(modal_relation)
            if include_tabs:
                tabs = self.tabs()
                tabs['hx-swap-oob'] = 'outerHTML:#workspace-tabs'
                workspace.add(tabs)
        return workspace

    def welcome(self):
        try:
            self.pool.get('nantic.chat.conversation')
            assistant_available = True
        except KeyError:
            assistant_available = False
        text = {
            'title': translate('What do you want to do?'),
            'search': translate(
                'Search 🔍︎ or chat with the assistant✦'
                if assistant_available else 'Search 🔍︎'),
            'menu': translate('Menu'),
            'help': translate('Help and Updates'),
            'favorites': translate('Favorites'),
            'profile': translate('Change preferences and company'),
            'resize': translate('Resize'),
            }
        Favorite = self.pool.get('ir.ui.menu.favorite')
        OpenMenu = self.pool.get('cassini.open.menu')
        panel = self.interface.component(
            'shell', {}).get('panel', 'none')
        with div(cls='vs-welcome'):
            with div(
                    cls='vs-welcome-hints',
                    aria_hidden='true'):
                if panel == 'none':
                    self.welcome_hint(text['menu'], 'vs-hint-menu')
                    if assistant_available:
                        self.welcome_hint(text['help'], 'vs-hint-help')
                    self.welcome_hint(
                        text['favorites'], 'vs-hint-favorites')
                self.welcome_hint(text['profile'], 'vs-hint-profile')
                if panel in {'menu', 'help'}:
                    self.welcome_hint(
                        text['resize'], 'vs-hint-resize')
            with div(cls='vs-welcome-center'):
                h2(text['title'], cls='vs-welcome-title')
                with div(cls='vs-welcome-search-box'):
                    input_(
                        type='text',
                        cls='vs-welcome-search',
                        placeholder=text['search'],
                        aria_label=text['search'],
                        autocomplete='off',
                        data_welcome_search='true')
                favorites = Favorite.get()
                if favorites:
                    with nav(
                            cls='vs-welcome-favorites',
                            aria_label=text['favorites']):
                        for menu_id, name, _icon_name in favorites:
                            with button(
                                    type='button',
                                    cls='vs-welcome-favorite',
                                    hx_post=OpenMenu.url(menu=menu_id),
                                    hx_target='#workspace',
                                    hx_swap='outerHTML',
                                    hx_push_url='true'):
                                icon('star')
                                span(name)

    @staticmethod
    def welcome_hint(label_, class_):
        arrow = (
            '<svg class="vs-welcome-arrow" viewBox="0 0 60 100" '
            'preserveAspectRatio="none" aria-hidden="true">'
            '<path d="M30 95 Q20 65 25 30" fill="none" '
            'stroke="currentColor" stroke-width="3.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            '<polygon points="25,15 18,30 25,25 32,30" '
            'fill="currentColor"/></svg>')
        with div(cls='vs-welcome-hint ' + class_):
            raw(arrow)
            span(label_, cls='vs-welcome-hint-label')

    def tabs(self):
        ActivateTab = self.pool.get('cassini.activate.tab')
        CloseTab = self.pool.get('cassini.close.tab')
        active = self.interface.active_tab
        active_tab = active['id'] if active else None
        if (active
                and active.get('kind') == 'wizard'
                and not active.get('window')):
            active_tab = active.get('return_tab')
        elif active and active.get('relation_modal'):
            active_tab = active.get('return_tab')
        with nav(
                id='workspace-tabs',
                cls='vs-tabs vs-tab-strip',
                aria_label=translate('Open tabs')) as tabs:
            with ul(cls='vs-tab-list', role='tablist'):
                for tab in self.interface.tabs:
                    if (tab.get('kind') == 'wizard'
                            and not tab.get('window')
                            or tab.get('relation_modal')):
                        continue
                    with li(
                            cls='vs-tab%s' % (
                                ' vs-tab-active' if tab['id'] == active_tab
                                else '')):
                        button(
                            tab['title']
                            + (' •' if tab.get('dirty') else ''),
                            type='button',
                            role='tab',
                            aria_selected=str(
                                tab['id'] == active_tab).lower(),
                            cls='vs-tab-title',
                            data_screen_owner=(
                                'screen-' + active_tab
                                if active_tab else None),
                            hx_post=ActivateTab.url(tab=tab['id']),
                            hx_target='#workspace',
                            hx_swap='outerHTML',
                            hx_push_url='true')
                        button(
                            '×', type='button',
                            aria_label=translate(
                                'Close %(tab)s', tab=tab['title']),
                            cls='vs-tab-close',
                            data_screen_owner=(
                                'screen-' + active_tab
                                if active_tab else None),
                            hx_post=CloseTab.url(tab=tab['id']),
                            hx_target='#workspace',
                            hx_swap='outerHTML')
        return tabs

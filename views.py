import calendar as month_calendar
import re
from datetime import date, datetime
from xml.etree import ElementTree

from dominate.tags import (
    a, article, button, col, colgroup, details, div, fieldset, form, h2, h3,
    header, hr, img, input_, label, legend, li, nav, option, p, section,
    select, span, summary, table, tbody, td, th, thead, tfoot, tr, ul)
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
                'string' not in node.attrib
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
        tab = dict(tab)
        tab['screen_width'] = self.interface.data.get('screen_width')
        view = decode_value(tab.get('view', {}))
        screen = section(
            id='screen-' + tab['id'],
            cls='vs-screen',
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

    def relation_dialog_header(self, tab):
        SelectNeighbor = self.pool.get('cassini.select.neighbor')
        current = tab.get('current_record')
        record_order = tab.get('record_order', [])
        position = (
            record_order.index(current) + 1
            if tab.get('relation_navigation')
            and current in record_order else 0)
        with header(cls='vs-relation-dialog-header') as header_:
            h2(tab['title'], cls='vs-relation-dialog-title')
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
        RunToolbarAction = self.pool.get('cassini.toolbar.action')

        current = tab.get('current_record')
        record = tab.get('records', {}).get(current) if current else None
        record_order = tab.get('record_order', [])
        relation_position = (
            record_order.index(current) + 1
            if tab.get('relation_navigation')
            and current in record_order else 0)
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
                        'href': (
                            category == 'print'
                            and action.get('type') == 'ir.action.report'),
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
            with details(cls='vs-popup vs-window-menu'):
                with summary(cls='vs-window-title'):
                    span(tab['title'], cls='vs-window-title-text')
                    if tab.get('dirty'):
                        span('•', cls='vs-window-dirty', title=translate('Unsaved'))
                        span(
                            translate('Unsaved changes'),
                            cls='vs-window-dirty-status')
                    span('▾', cls='vs-window-title-caret')
                with div(
                        cls='vs-popup-menu vs-window-menu-list',
                        role='menu'):
                    span(translate('Views'), cls='vs-popup-heading')
                    view_titles = {
                        'tree': translate('Tree'),
                        'form': translate('Form'),
                        'list-form': translate('List Form'),
                        'calendar': translate('Calendar'),
                        }
                    for view_type in tab.get('view_types', []):
                        button(
                            view_titles.get(view_type, view_type),
                            type='button',
                            cls='vs-popup-item%s' % (
                                ' vs-button-active'
                                if tab.get('view_type') == view_type else ''),
                            hx_post=SwitchView.url(
                                tab=tab['id'], view=view_type),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML',
                            data_view_type=view_type)
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
                    a(
                        translate('Export selected fields'),
                        href=ExportRecords.url(tab=tab['id']),
                        cls='vs-popup-item', role='menuitem')
                    for export in toolbar_data.get('exports', []):
                        a(
                            export['name'],
                            href=ExportRecords.url(
                                tab=tab['id'],
                                export_id=export['id']),
                            cls='vs-popup-item', role='menuitem')
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
                                for_='import-' + tab['id'],
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
                with div(cls='vs-toolbar-group', role='group'):
                    for resource, image, title in (
                            ('attachments', 'attach',
                                translate('Attachments')),
                            ('notes', 'note', translate('Notes'))):
                        with button(
                                type='button', cls='vs-icon-button',
                                title=title, aria_label=title,
                                disabled=(
                                    not record or record.get('new') or None),
                                data_shortcut_action=(
                                    'attach'
                                    if resource == 'attachments'
                                    else 'note'),
                                hx_post=OpenRelated.url(
                                    tab=tab['id'], resource=resource),
                                hx_target='#workspace',
                                hx_swap='outerHTML',
                                hx_push_url='true'):
                            icon(image)
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
                                span(translate('No actions'), cls='vs-popup-empty')
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
        SelectNeighbor = self.pool.get('cassini.select.neighbor')
        SearchBookmarkDialog = self.pool.get(
            'cassini.search.bookmark.dialog')
        DeleteSearchBookmark = self.pool.get(
            'cassini.delete.search.bookmark')
        ApplySearchBookmark = self.pool.get(
            'cassini.apply.search.bookmark')
        ViewSearch = self.pool.get('ir.ui.view_search')

        view = decode_value(tab.get('view', {}))
        definitions = search_field_definitions(view)
        search_filters = decode_value(tab.get('search_filters', {}))
        search_domain = decode_value(tab.get('search_domain', []))
        bookmarks = ViewSearch.get().get(tab['model'], [])
        current_bookmark = next((
                bookmark for bookmark in bookmarks
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
            with form(
                    cls='vs-search-form',
                    hx_post=Search.url(tab=tab['id']),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML'):
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
            if current_bookmark and current_bookmark[3]:
                with button(
                        type='button', cls='vs-icon-button',
                        title=translate('Remove this bookmark'),
                        aria_label=translate('Remove this bookmark'),
                        hx_post=DeleteSearchBookmark.url(
                            tab=tab['id'],
                            bookmark=current_bookmark[0]),
                        hx_target='#screen-' + tab['id'],
                        hx_swap='outerHTML'):
                    icon('star')
            else:
                with button(
                        type='button', cls='vs-icon-button',
                        title=translate('Bookmark this filter'),
                        aria_label=translate('Bookmark this filter'),
                        disabled=not search_domain or None,
                        hx_get=SearchBookmarkDialog.url(
                            tab=tab['id']),
                        hx_target='#modal',
                        hx_swap='innerHTML'):
                    icon(
                        'star'
                        if current_bookmark else 'star-border')
            with details(cls='vs-popup vs-bookmark-popup'):
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
            with div(
                    cls='vs-search-navigation',
                    role='group', aria_label=translate('Search navigation')):
                for direction, image, title in (
                        ('previous', 'back', translate('Previous record')),
                        ('next', 'forward', translate('Next record'))):
                    with button(
                            type='button', cls='vs-icon-button',
                            title=title, aria_label=title,
                            disabled=not tab.get('record_order') or None,
                            data_shortcut_action=direction,
                            hx_post=SelectNeighbor.url(
                                tab=tab['id'], direction=direction),
                            hx_target='#screen-' + tab['id'],
                            hx_swap='outerHTML'):
                        icon(image)
        return search_toolbar

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
        editable = (
            root.attrib.get('editable') in {'top', 'bottom', '1'}
            and tab.get('access', {}).get('write', True)
            and not decode_value(
                tab.get('context', {})).get('_datetime'))
        all_buttons = [
            node for node in root
            if node.tag == 'button'
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
            tree_invisible = str(
                node.attrib.get('tree_invisible', '0')).lower() in {
                    '1', 'true', 'yes'}
            if visible and not tree_invisible:
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
        sequence_field = root.attrib.get('sequence')
        select_column_class = (
            'vs-select-column vs-sequence-column'
            if sequence_field and editable else 'vs-select-column')
        rows = self.tree_rows(tab, view)
        first_field = next((
                node.attrib['name']
                for node in columns if node.tag == 'field'), None)
        with div(cls='vs-table-wrap') as wrapper:
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
                    cls='vs-table vs-resizable-table',
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
                                                            ToggleColumn.url(
                                                                tab=tab['id'],
                                                                field=name)),
                                                        hx_trigger='change',
                                                        hx_target=(
                                                            '#screen-'
                                                            + tab['id']),
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
                                input_(
                                    type='checkbox', name='selected',
                                    value='true',
                                    checked=bool(tab.get('record_order'))
                                    and len(tab.get('selected', []))
                                    == len(tab.get('record_order', []))
                                    or None,
                                    aria_label=translate('Select all records'),
                                    hx_post=SelectAll.url(tab=tab['id']),
                                    hx_trigger='change',
                                    hx_target='#screen-' + tab['id'],
                                    hx_swap='outerHTML',
                                    hx_include='this')
                        for node in columns:
                            if node.tag == 'field':
                                definition = view.get('fields', {}).get(
                                    node.attrib['name'], {})
                                with th():
                                    button(
                                        node.attrib.get('string')
                                        or definition.get('string')
                                        or node.attrib['name'],
                                        type='button',
                                        cls='vs-sort-button',
                                        hx_post=SortRecords.url(
                                            tab=tab['id'],
                                            field=node.attrib['name']),
                                        hx_target='#screen-' + tab['id'],
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
                            tab, record, view, editable=editable)
                        row_visual = renderer.evaluate(
                            root.attrib.get('visual'))
                        row_visual = (
                            row_visual
                            if row_visual in {
                                'muted', 'success', 'warning', 'danger'}
                            else None)
                        with tr(
                                cls='vs-row%s%s%s' % (
                                    ' vs-row-current'
                                    if key == tab.get('current_record') else '',
                                    ' vs-row-dirty'
                                    if record.get('dirty') else '',
                                    ' vs-visual-' + row_visual
                                    if row_visual else ''),
                                data_record=key):
                            with td(cls=select_column_class):
                                input_(
                                    type='checkbox', name='selected',
                                    value='true',
                                    checked=key in tab.get('selected', [])
                                    or None,
                                    aria_label=translate('Select record'),
                                    hx_post=SelectRecord.url(
                                        tab=tab['id'], record=key),
                                    hx_trigger='change',
                                    hx_target='#screen-' + tab['id'],
                                    hx_swap='outerHTML',
                                    hx_include='this')
                                button(
                                    '', type='button',
                                    cls='vs-row-action',
                                    tabindex='-1',
                                    aria_hidden='true',
                                    data_row_select_action='true',
                                    hx_post=SelectRecord.url(
                                        tab=tab['id'], record=key,
                                        row='true', silent='true'),
                                    hx_target='#screen-' + tab['id'],
                                    hx_swap='none')
                                button(
                                    '', type='button',
                                    cls='vs-row-action',
                                    tabindex='-1',
                                    aria_hidden='true',
                                    data_row_open_action='true',
                                    hx_post=SelectRecord.url(
                                        tab=tab['id'], record=key,
                                        row='true', open='true'),
                                    hx_target='#screen-' + tab['id'],
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
                                                        MoveTreeRecord.url(
                                                            tab=tab['id'],
                                                            record=key,
                                                            direction=(
                                                                direction))),
                                                    hx_target=(
                                                        '#screen-'
                                                        + tab['id']),
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
                                                        ToggleTreeNode.url(
                                                            tab=tab['id'],
                                                            record=key)),
                                                    hx_target=(
                                                        '#screen-'
                                                        + tab['id']),
                                                    hx_swap='outerHTML')
                                                toggle.add(icon(
                                                        'arrow-down'
                                                        if is_expanded else
                                                        'arrow-right'))
                                            with div(
                                                    cls=(
                                                        'vs-tree-content')) \
                                                    as content:
                                                for affix in node:
                                                    if affix.tag == 'prefix':
                                                        self.tree_affix(
                                                            renderer, affix)
                                                if editable:
                                                    renderer.render(
                                                        name, node.attrib,
                                                        compact=True)
                                                else:
                                                    renderer.display(
                                                        name, node.attrib)
                                                for affix in node:
                                                    if affix.tag == 'suffix':
                                                        self.tree_affix(
                                                            renderer, affix)
                                            cell_depth = (
                                                depth
                                                if name == first_field else 0)
                                            HierarchyWidget.row(
                                                content, toggle, cell_depth,
                                                is_expanded,
                                                extra_class=(
                                                    'vs-tree-hierarchy'))
                                    else:
                                        attributes = dict(node.attrib)
                                        readonly, _, invisible = (
                                            renderer.states({}, attributes))
                                        if not invisible:
                                            attributes['_state_readonly'] = (
                                                readonly)
                                            self.record_button(
                                                tab, record, attributes)
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
                p(translate('No records'), cls='vs-empty')
            selected = [
                key for key in tab.get('selected', [])
                if key in tab.get('records', {})]
            if selected and multiple_buttons:
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
                            attributes)
            self.pagination(wrapper, tab)
        return wrapper

    def tree_affix(self, renderer, node):
        attributes = node.attrib
        value = renderer.values.get(attributes.get('name'))
        icon_name = attributes.get('icon')
        type_ = attributes.get('icon_type', 'icon')
        if type_ == 'url' and value:
            img(
                src=value,
                alt=attributes.get('string', ''),
                cls='vs-tree-affix')
        elif type_ == 'color' and value:
            span(
                '', cls='vs-tree-affix vs-tree-affix-color',
                style='background-color: %s' % value,
                title=attributes.get('string', ''))
        elif icon_name:
            icon(
                icon_name.removeprefix('tryton-'),
                attributes.get('string'),
                cls='vs-icon vs-tree-affix')
        elif value not in (None, ''):
            span(stringify(value), cls='vs-tree-affix')
        elif attributes.get('string'):
            span(attributes['string'], cls='vs-tree-affix')

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

    def pagination(self, parent, tab):
        PageRecords = self.pool.get('cassini.page.records')
        offset = int(tab.get('offset') or 0)
        limit = int(tab.get('limit') or 100)
        count = int(tab.get('count') or len(tab.get('record_order', [])))
        if count > limit or offset:
            with nav(
                    cls='vs-pagination',
                    aria_label=translate('Record pages')) as pagination:
                button(
                    translate('Previous'), type='button', cls='vs-button',
                    disabled=offset <= 0 or None,
                    hx_post=PageRecords.url(
                        tab=tab['id'], direction='previous'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML')
                span(
                    '%d–%d of %d' % (
                        offset + 1 if count else 0,
                        min(offset + limit, count), count))
                button(
                    translate('Next'), type='button', cls='vs-button',
                    disabled=offset + limit >= count or None,
                    hx_post=PageRecords.url(
                        tab=tab['id'], direction='next'),
                    hx_target='#screen-' + tab['id'],
                    hx_swap='outerHTML')
            parent.add(pagination)

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
        try:
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
        xexpand = str(attributes.get('xexpand', '1')).lower() not in {
            '0', 'false', 'no'}
        xfill = str(attributes.get('xfill', '1')).lower() not in {
            '0', 'false', 'no'}
        if xexpand and xfill:
            rules.append('width:100%')
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
            'minmax(min-content, 1fr)'
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
                            ' vs-hidden' if scan_invisible else '')):
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
                columns=root.attrib.get('col', 4))
        return tag

    def form_children(
            self, parent, node, renderer, tab, record, path=(),
            inherited_readonly=False, columns=4):
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
        for index, child in enumerate(node):
            attributes = dict(child.attrib)
            child_path = path + (index,)
            if (
                    attributes.get('name') == tab.get('exclude_field')
                    and child.tag in {
                        'field', 'label', 'separator', 'page', 'group'}):
                continue
            if child.tag == 'label':
                attributes.setdefault('xexpand', '0')
                attributes.setdefault('xalign', '1.0')
                attributes.setdefault('yalign', '0.5')
            if child.tag in {'notebook', 'hpaned', 'vpaned'}:
                attributes.setdefault('colspan', '4')
            layout_style = self.form_layout_style(attributes, columns)
            if child.tag == 'newline':
                layout_style = 'grid-column:1/-1'
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
                    for_=(
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
                parent.add(self.record_button(tab, record, attributes))
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
                    and page.attrib.get('name') != tab.get('exclude_field')
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
            elif child.tag == 'newline':
                parent.add(div(
                        cls='vs-newline', style=layout_style))
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
                    record=record['id']),
                hx_target='#workspace',
                hx_swap='outerHTML') as control:
            if attributes.get('icon'):
                icon(attributes['icon'].removeprefix('tryton-'))
            span(title, cls='vs-link-title')
            if domain_titles:
                for name, count in zip(domain_titles, counts):
                    with span(cls='vs-link-domain'):
                        span(name)
                        span(
                            '99+' if count > 99 else str(count),
                            cls='vs-link-count')
            elif counts:
                span(
                    '99+' if counts[0] > 99 else str(counts[0]),
                    cls='vs-link-count')
        return control

    def record_button(self, tab, record, attributes):
        RunButton = self.pool.get('cassini.run.button')
        with button(
                type='button',
                cls=attributes.get('_class', 'vs-button'),
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
            if attributes.get('icon'):
                icon(attributes['icon'].removeprefix('tryton-'))
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
            'values': values,
            'x2many': tab.setdefault('x2many', {}),
            }
        renderer = WidgetRenderer(
            pseudo_tab, pseudo_record, view,
            editable=True, endpoint='wizard')
        root = parse_architecture(view)
        wizard = form(
            id='wizard-' + tab['id'],
            cls='vs-form vs-wizard')
        wizard.add(h2(
                tab['title'], id='wizard-title-' + tab['id']))
        content = div(
            cls='vs-form vs-wizard-content',
            style=self.form_grid_style(
                root, root.attrib.get('col', 4)))
        self.form_children(
            content, root, renderer, pseudo_tab, pseudo_record,
            columns=root.attrib.get('col', 4))
        wizard.add(content)
        with div(cls='vs-dialog-actions') as actions:
            for definition in decode_value(tab.get('buttons', [])):
                button(
                    definition['string'], type='button',
                    cls='vs-button%s' % (
                        ' vs-button-primary'
                        if definition.get('default') else ''),
                    hx_post=WizardStep.url(
                        tab=tab['id'], state=definition['state']),
                    hx_include='closest form',
                    hx_target='#workspace',
                    hx_swap='outerHTML')
        wizard.add(actions)
        return wizard

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
                                cls='vs-modal vs-wizard-dialog'):
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
                            hx_post=ActivateTab.url(tab=tab['id']),
                            hx_target='#workspace',
                            hx_swap='outerHTML',
                            hx_push_url='true')
                        button(
                            '×', type='button',
                            aria_label=translate(
                                'Close %(tab)s', tab=tab['title']),
                            cls='vs-tab-close',
                            hx_post=CloseTab.url(tab=tab['id']),
                            hx_target='#workspace',
                            hx_swap='outerHTML')
        return tabs

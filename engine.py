import base64
import codecs
import csv
import io
import json
import math
import mimetypes
import uuid
import zlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from sql import For
from trytond import backend
from trytond.modules.xgettext import _
from trytond.pool import Pool
from trytond.pyson import PYSONDecoder, PYSONEncoder
from trytond.tools import timezone
from trytond.transaction import Transaction

from .search import (
    COMMON_SEARCH_FIELDS as SEARCH_COMMON_SEARCH_FIELDS,
    date_format, parse_date, search_domain_parser,
    search_field_definitions, time_format, to_server_datetime)
from werkzeug.wrappers import Response
from werkzeug.utils import secure_filename

from .state import InterfaceState, decode_value, encode_value
from .widgets import WidgetRenderer

SUPPORTED_VIEWS = {'tree', 'form', 'list-form', 'calendar'}
COMMON_SEARCH_FIELDS = SEARCH_COMMON_SEARCH_FIELDS
TREE_RECORD_CHUNK_SIZE = 100
RECORD_COUNT_LIMIT = 1000
SHARED_TAB_VERSION = 1
SHARED_TAB_MAX_LENGTH = 65536


def encode_shared_tab(tab):
    """Encode the portable state of a window tab for a share URL."""
    if tab.get('kind') != 'window' or tab.get('relation_modal'):
        raise ValueError(_('Only window tabs can be shared'))
    names = (
        'model', 'title', 'domain', 'context_domain', 'domain_tabs',
        'active_domain', 'search_value', 'search', 'search_domain',
        'search_filters', 'active_only', 'order', 'default_order',
        'view_ids', 'view_types', 'view_type', 'limit')
    values = {
        name: tab.get(name)
        for name in names
        }
    values['default_order'] = tab.get(
        'default_order', tab.get('order'))
    values['version'] = SHARED_TAB_VERSION
    if tab.get('view_type') == 'form':
        record = tab.get('records', {}).get(tab.get('current_record'))
        if record and int(record.get('id') or 0) > 0:
            values['res_id'] = int(record['id'])
    raw = json.dumps(
        values, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > SHARED_TAB_MAX_LENGTH:
        raise ValueError(_('The current filter is too large to share'))
    compressed = zlib.compress(raw, level=9)
    return base64.urlsafe_b64encode(compressed).rstrip(b'=').decode('ascii')


def decode_shared_tab(payload):
    """Decode and minimally validate portable window state."""
    if not payload or len(payload) > SHARED_TAB_MAX_LENGTH * 2:
        raise ValueError(_('Invalid shared tab'))
    try:
        encoded = payload.encode('ascii')
        encoded += b'=' * (-len(encoded) % 4)
        compressed = base64.b64decode(
            encoded, altchars=b'-_', validate=True)
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(
            compressed, SHARED_TAB_MAX_LENGTH + 1)
        if (len(raw) > SHARED_TAB_MAX_LENGTH
                or decompressor.unconsumed_tail
                or decompressor.unused_data
                or not decompressor.eof):
            raise ValueError
        values = json.loads(raw.decode())
    except (
            UnicodeError, ValueError, TypeError, json.JSONDecodeError,
            zlib.error):
        raise ValueError(_('Invalid shared tab'))
    if (not isinstance(values, dict)
            or values.get('version') != SHARED_TAB_VERSION
            or not isinstance(values.get('model'), str)):
        raise ValueError(_('Invalid shared tab'))
    return values


def evaluate(value, context, default=None):
    if value in (None, ''):
        return default
    if not isinstance(value, str):
        return value
    try:
        return PYSONDecoder(context).decode(value)
    except Exception:
        return default


def combine_domains(*domains):
    domains = [domain for domain in domains if domain]
    if not domains:
        return []
    if len(domains) == 1:
        return domains[0]
    return ['AND', *domains]


def menu_action_url(menu):
    """Return the external URL configured as a menu action, if any."""
    action = menu.action
    if action and action.__name__ == 'ir.action.url':
        return action.url
    return None


class SaoEngine:
    """Translate Tryton client semantics into a persistent state document."""

    def __init__(self, workspace):
        self.pool = Pool()
        self.open_urls = []
        Workspace = self.pool.get('cassini.workspace')
        # HTMX requests from different parts of the same workspace may arrive
        # concurrently. ModelSQL.lock uses NOWAIT, which turns a normal overlap
        # with a long-running request into a database error. A blocking row
        # lock serialises the state document so every request reads the latest
        # committed revision.
        if backend.name != 'sqlite':
            table = Workspace.__table__()
            cursor = Transaction().connection.cursor()
            cursor.execute(*table.select(
                    table.id,
                    where=table.id == workspace.id,
                    for_=For('UPDATE')))
        values, = Workspace.read(
            [workspace.id], ['state', 'revision'])
        workspace.state = values['state']
        workspace.revision = values['revision']
        self.workspace = workspace
        self.interface = InterfaceState(decode_value(values['state']))

    @property
    def user(self):
        return self.workspace.user

    def save(self):
        self.workspace.store(self.interface)

    def context(self, extra=None, data=None):
        User = self.pool.get('res.user')
        context = dict(User.get_preferences(context_only=True))
        context.update(Transaction().context)
        data = data or {}
        context.update({
                'active_model': data.get('model'),
                'active_id': data.get('id'),
                'active_ids': data.get('ids', []),
                '_user': Transaction().user,
                })
        if extra:
            context.update(extra)
        return context

    def start_user_actions(self, action_ids):
        """Execute the login actions from the user preferences like Sao."""
        if 'startup_actions' in self.interface.data:
            return
        self.interface.data['startup_actions'] = list(action_ids or [])
        self._start_next_user_actions()
        self.save()

    def _start_next_user_actions(self):
        actions = self.interface.data.setdefault('startup_actions', [])
        while actions:
            action_id = actions.pop(0)
            opened = self.open_action(action_id)
            if (opened
                    and not isinstance(opened, Response)
                    and opened.get('kind') == 'wizard'):
                opened['startup_action'] = True
                break

    def open_menu(self, menu_id):
        ActionKeyword = self.pool.get('ir.action.keyword')
        actions = ActionKeyword.get_keyword(
            'tree_open', ('ir.ui.menu', int(menu_id)))
        if not actions:
            raise ValueError(_('This menu does not define an action'))
        return self.open_action(actions[0], {
                'model': 'ir.ui.menu',
                'id': int(menu_id),
                'ids': [int(menu_id)],
                })

    def open_resource(self, model_name, record_id, title=None):
        Model = self.pool.get(model_name)
        record_id = int(record_id)
        record = Model(record_id)
        action = {
            'id': None,
            'name': title or record.rec_name,
            'type': 'ir.action.act_window',
            'res_model': model_name,
            'res_id': record_id,
            'views': [],
            'domains': [],
            'pyson_domain': '[]',
            'pyson_context': '{}',
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': 100,
            }
        return self.open_action(action, {
                'model': model_name,
                'id': record_id,
                'ids': [record_id],
                })

    def open_relation_modal(
            self, parent_tab_id, model_name, record_id, title=None,
            record_ids=None):
        parent = self._tab(parent_tab_id)
        if parent.get('kind') not in {'window', 'wizard'}:
            raise ValueError(_('Unknown relation parent'))
        Model = self.pool.get(model_name)
        record_id = int(record_id)
        record = Model(record_id)
        action = {
            'id': None,
            'name': title or record.rec_name,
            'type': 'ir.action.act_window',
            'res_model': model_name,
            'res_id': record_id,
            'views': [],
            'domains': [],
            'pyson_domain': '[]',
            'pyson_context': '{}',
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': 100,
            }
        tab = self._open_window(
            action, {
                'model': model_name,
                'id': record_id,
                'ids': [record_id],
                }, None, reuse=False)
        if record_ids:
            record_ids = list(dict.fromkeys(
                    int(id_) for id_ in record_ids if id_))
            if record_id not in record_ids:
                record_ids.append(record_id)
            self.load_tab(tab, ids=record_ids)
            tab['current_record'] = str(record_id)
            tab['selected'] = [str(record_id)]
            tab['relation_navigation'] = True
        tab['relation_modal'] = True
        tab['return_tab'] = parent['id']
        self.save()
        return tab

    def open_related(self, tab_id, resource):
        tab = self._tab(tab_id, kind='window')
        key = tab.get('current_record')
        record = tab.get('records', {}).get(key)
        if not record or not record.get('id'):
            raise ValueError(_('Select a saved record first'))
        resources = {
            'attachments': ('ir.attachment', _('Attachments')),
            'notes': ('ir.note', _('Notes')),
            'logs': ('ir.model.log', _('Logs')),
            }
        try:
            model_name, title = resources[resource]
        except KeyError:
            raise ValueError(_('Unknown related resource'))
        reference = '%s,%s' % (tab['model'], record['id'])
        Model = self.pool.get(tab['model'])
        rec_name = str(Model(record['id']).rec_name)
        action = {
            'id': None,
            'name': '%s (%s)' % (title, rec_name),
            'type': 'ir.action.act_window',
            'res_model': model_name,
            'views': [],
            'domains': [],
            'pyson_domain': json.dumps([
                    ('resource', '=', reference)]),
            'pyson_context': json.dumps({
                    'default_resource': reference}),
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': 100,
            }
        data = {
                'model': tab['model'],
                'id': record['id'],
                'ids': [record['id']],
                }
        if resource == 'logs':
            return self.open_action(action, data)
        related = self._open_window(action, data, None, reuse=False)
        related['relation_modal'] = True
        related['return_tab'] = tab['id']
        if not tab.get('access', {}).get('write', True):
            related['access']['create'] = False
            related['access']['write'] = False
            related['access']['delete'] = False
        if resource == 'notes':
            Note = self.pool.get('ir.note')
            notes = Note.search([
                    ('resource', '=', reference),
                    ('unread', '=', True),
                    ])
            if notes:
                Note.write(notes, {'unread': False})
                self.load_tab(related)
        self._set_resource_relation(related, reference, title)
        self.save()
        return related

    def _set_resource_relation(self, tab, reference, title):
        """Use the shared one2many widget for resource records.

        Attachments and notes are linked through their ``resource`` reference,
        not through a field on every possible model.  The popup therefore owns
        a small virtual one2many field while retaining the regular resource
        model and its access rules.
        """
        field = 'resource_items'
        view = {
            'model': tab['model'],
            'arch': (
                '<form col="1"><field name="%s" '
                'mode="tree,form"/></form>' % field),
            'fields': {
                field: {
                    'type': 'one2many',
                    'string': title,
                    'relation': tab['model'],
                    'relation_field': 'resource',
                    },
                },
            }
        tab['resource_relation'] = {
            'field': field,
            'reference': reference,
            }
        tab.update({
                'view': encode_value(view),
                'view_type': 'form',
                'view_types': ['form'],
                'view_ids': [None],
                'records': {
                    'resource': {
                        'key': 'resource',
                        'id': None,
                        'values': encode_value({field: []}),
                        'baseline': encode_value({field: []}),
                        'dirty': [],
                        'new': False,
                        'deleted': False,
                        'x2many': {},
                        },
                    },
                'record_order': ['resource'],
                'current_record': 'resource',
                'selected': ['resource'],
                'dirty': False,
                })
        self.refresh_resource_relation(tab)

    def refresh_resource_relation(self, tab):
        """Refresh the virtual one2many list, preserving pending deletes."""
        relation = tab.get('resource_relation') or {}
        field = relation.get('field')
        record = tab.get('records', {}).get('resource')
        if not field or not record:
            return tab
        state = record.setdefault('x2many', {}).setdefault(field, {
                'view': 'tree',
                'current': None,
                'deleted': [],
                })
        deleted_ids = {
            item.get('id') if isinstance(item, dict) else int(item)
            for item in state.get('deleted', [])
            if (isinstance(item, dict) and item.get('id'))
            or str(item).lstrip('-').isdigit()
            }
        Resource = self.pool.get(tab['model'])
        resources = Resource.search([
                ('resource', '=', relation['reference']),
                ])
        values = decode_value(record.get('values', {}))
        values[field] = [
            resource.id for resource in resources
            if resource.id not in deleted_ids]
        record['values'] = encode_value(values)
        return tab

    def save_resource_relation(self, tab_id):
        """Persist changes from a virtual resource one2many field."""
        tab = self._tab(tab_id, kind='window')
        relation = tab.get('resource_relation')
        if not relation:
            return tab
        field = relation['field']
        record = tab['records']['resource']
        values = decode_value(record.get('values', {}))
        state = record.setdefault('x2many', {}).setdefault(field, {})
        deleted_ids = {
            item.get('id') if isinstance(item, dict) else int(item)
            for item in state.get('deleted', [])
            if (isinstance(item, dict) and item.get('id'))
            or str(item).lstrip('-').isdigit()
            }
        Resource = self.pool.get(tab['model'])
        creates = []
        writes = []
        for item in values.get(field, []):
            if not isinstance(item, dict):
                continue
            item_values = decode_value(item.get('values', item))
            item_values.pop('__key__', None)
            item_values = self._record_values(Resource, item_values)
            if item.get('id'):
                if item_values:
                    writes.append((item['id'], item_values))
            elif item_values:
                item_values['resource'] = relation['reference']
                creates.append(item_values)
        context = self.context(decode_value(tab.get('context', {})))
        with Transaction().set_context(context):
            if creates:
                Resource.create(creates)
            for resource_id, write_values in writes:
                Resource.write([Resource(resource_id)], write_values)
            if deleted_ids:
                resources = Resource.search([
                        ('id', 'in', list(deleted_ids)),
                        ('resource', '=', relation['reference']),
                        ])
                Resource.delete(resources)
        state['deleted'] = []
        self.refresh_resource_relation(tab)
        self.save()
        return tab

    def open_action(self, action, data=None, extra_context=None):
        data = data or {}
        action = self.action_value(action)
        action_type = action.get('type')
        if action_type == 'ir.action.act_window':
            tab = self._open_window(action, data, extra_context)
        elif action_type == 'ir.action.wizard':
            tab = self._open_wizard(action, data, extra_context)
        elif action_type == 'ir.action.report':
            return self.execute_report(action, data, extra_context)
        elif action_type == 'babi.action.dashboard':
            tab = self._open_dashboard(
                action, data, extra_context)
        elif action_type == 'ir.action.url':
            self.open_urls.append(action['url'])
            return None
        elif action_type == 'nantic.action.open_conversation':
            try:
                Conversation = self.pool.get(
                    'nantic.chat.conversation')
            except KeyError:
                raise ValueError(
                    _('Unsupported action type %s') % action_type)
            identifier = (
                action.get('identifier') or action.get('res_id'))
            conversations = Conversation.search([
                    ('identifier', '=', identifier),
                    ('create_uid', '=', Transaction().user),
                    ], limit=1)
            if not conversations:
                raise ValueError(_('Unknown conversation'))
            conversation, = conversations
            shell = self.interface.component('shell', {
                    'panel': 'none',
                    'theme': 'light',
                    'user_menu': False,
                    })
            shell['panel'] = 'help'
            shell['user_menu'] = False
            assistant = self.interface.component('assistant', {
                    'section': 'assistant',
                    'conversation': None,
                    'nan': None,
                    })
            assistant['section'] = 'assistant'
            assistant['conversation'] = conversation.identifier
            agent = conversation.get_agent_info()
            assistant['nan'] = agent.get('id') if agent else None
            conversation.mark_assistant_messages_as_read()
            tab = None
        else:
            raise ValueError(_('Unsupported action type %s') % action_type)
        self.save()
        return tab

    def _open_dashboard(self, action, data, extra_context):
        try:
            self.pool.get('babi.dashboard')
            self.pool.get('babi.widget')
        except KeyError:
            raise ValueError(_(
                'The Dashboard view requires the babi module.'))
        dashboard_id = action.get('dashboard')
        if not dashboard_id:
            raise ValueError(_('Unknown dashboard'))
        context = dict(extra_context or {})
        for tab in self.interface.tabs:
            if (
                    tab.get('kind') == 'dashboard'
                    and int(tab.get('dashboard') or 0) == int(dashboard_id)
                    and decode_value(tab.get('context', {})) == context):
                self.interface.activate(tab['id'])
                return tab
        tab = self.interface.add_tab({
                'kind': 'dashboard',
                'title': action.get('name') or _('Dashboard'),
                'dashboard': int(dashboard_id),
                'action': encode_value(action),
                'context': encode_value(context),
                'data': encode_value(data or {}),
                'dashboard_items': [],
                })
        self._load_dashboard(tab)
        return tab

    def _load_dashboard(self, tab):
        Dashboard = self.pool.get('babi.dashboard')
        Widget = self.pool.get('babi.widget')
        context = self.context(
            decode_value(tab.get('context', {})),
            decode_value(tab.get('data', {})))
        with Transaction().set_context(context):
            records = Dashboard.read(
                [int(tab['dashboard'])], ['name', 'view'])
            if not records:
                raise ValueError(_('Unknown dashboard'))
            dashboard = records[0]
            try:
                items = json.loads(dashboard.get('view') or '[]')
            except (TypeError, ValueError):
                items = []

            widget_ids = set()

            def collect(nodes):
                for node in nodes if isinstance(nodes, list) else []:
                    if not isinstance(node, dict):
                        continue
                    if node.get('widget'):
                        widget_ids.add(int(node['widget']))
                    collect(node.get('children', []))

            collect(items)
            charts = {
                record['id']: record.get('chart') or ''
                for record in Widget.read(
                    sorted(widget_ids), ['chart'])
                } if widget_ids else {}

        def prepare(nodes):
            result = []
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict) or not node.get('widget'):
                    continue
                widget_id = int(node['widget'])
                try:
                    colspan = max(1, min(4, int(node.get('colspan') or 1)))
                except (TypeError, ValueError):
                    colspan = 1
                try:
                    height = max(120, min(
                            2000, int(node.get('height') or 450)))
                except (TypeError, ValueError):
                    height = 450
                result.append({
                        'widget': widget_id,
                        'colspan': colspan,
                        'height': height,
                        'chart': charts.get(widget_id, ''),
                        'children': prepare(node.get('children', [])),
                        })
            return result

        tab['title'] = dashboard.get('name') or tab['title']
        tab['dashboard_items'] = encode_value(prepare(items))
        return tab

    def action_value(self, action):
        if isinstance(action, int):
            Action = self.pool.get('ir.action')
            action = Action(action).get_action_value()
        return action

    @staticmethod
    def _same_window(tab, values, explicit_view_ids):
        """Match an existing window using Sao's ``Tab.Form.compare`` rules."""
        if tab.get('kind') != 'window' or tab.get('relation_modal'):
            return False
        try:
            view_index = tab.get('view_types', []).index(
                tab.get('view_type'))
        except ValueError:
            return False
        return (
            view_index <= 0
            and tab.get('model') == values['model']
            and tab.get('res_id') == values['res_id']
            and decode_value(tab.get('domain', [])) == values['domain']
            and decode_value(tab.get(
                    'context_domain', [])) == values['context_domain']
            and tab.get('view_ids', []) == values['view_ids']
            and (
                explicit_view_ids
                or tab.get('view_types', ['tree', 'form'])
                == values['view_types'])
            and decode_value(tab.get('context', {})) == values['context']
            and decode_value(tab.get(
                    'search_value', [])) == values['search_value']
            and decode_value(tab.get(
                    'domain_tabs', [])) == values['domain_tabs'])

    def open_shared_window(self, values):
        """Replace the workspace tabs with one portable shared window."""
        model_name = values.get('model')
        if not isinstance(model_name, str) or not model_name:
            raise ValueError(_('Invalid shared tab'))
        self.pool.get(model_name)

        view_types = values.get('view_types')
        view_ids = values.get('view_ids')
        if not isinstance(view_types, list):
            view_types = []
        if not isinstance(view_ids, list):
            view_ids = []
        views = []
        View = self.pool.get('ir.ui.view')
        for index, view_type in enumerate(view_types):
            if view_type not in SUPPORTED_VIEWS:
                continue
            view_id = view_ids[index] if index < len(view_ids) else None
            if view_id is not None:
                try:
                    view_id = int(view_id)
                except (TypeError, ValueError):
                    view_id = None
                if view_id and not View.search([
                            ('id', '=', view_id),
                            ('model', '=', model_name),
                            ], limit=1):
                    view_id = None
            views.append((view_id, view_type))
        if not views:
            views = [(None, 'tree'), (None, 'form')]
        view_ids = [view_id for view_id, _view_type in views]
        view_types = [view_type for _view_id, view_type in views]
        view_type = values.get('view_type')
        if view_type not in view_types:
            view_type = view_types[0]
        view_id = view_ids[view_types.index(view_type)]

        domain = decode_value(values.get('domain') or [])
        context_domain = decode_value(values.get('context_domain') or [])
        search_value = decode_value(values.get('search_value') or [])
        search_domain = decode_value(values.get('search_domain') or [])
        for value in (domain, context_domain, search_value, search_domain):
            if not isinstance(value, list):
                raise ValueError(_('Invalid shared tab'))
        order = decode_value(values.get('order'))
        if order is not None and not isinstance(order, list):
            raise ValueError(_('Invalid shared tab'))
        default_order = decode_value(values.get('default_order'))
        if default_order is not None and not isinstance(default_order, list):
            raise ValueError(_('Invalid shared tab'))
        if 'default_order' not in values:
            default_order = order
        search_filters = decode_value(values.get('search_filters') or {})
        if not isinstance(search_filters, dict):
            raise ValueError(_('Invalid shared tab'))
        domain_tabs = decode_value(values.get('domain_tabs') or [])
        if not isinstance(domain_tabs, list):
            raise ValueError(_('Invalid shared tab'))
        domain_tabs = [
            {
                'name': str(domain_tab.get('name') or ''),
                'domain': domain_tab.get('domain') or [],
                'count': bool(domain_tab.get('count')),
                }
            for domain_tab in domain_tabs
            if (isinstance(domain_tab, dict)
                and isinstance(domain_tab.get('domain') or [], list))
            ]
        try:
            active_domain = int(values.get('active_domain') or 0)
        except (TypeError, ValueError):
            active_domain = 0
        if not 0 <= active_domain < len(domain_tabs):
            active_domain = 0
        try:
            limit = int(values.get('limit') or RECORD_COUNT_LIMIT)
        except (TypeError, ValueError):
            limit = RECORD_COUNT_LIMIT
        limit = max(1, min(limit, RECORD_COUNT_LIMIT))
        try:
            res_id = int(values.get('res_id') or 0) or None
        except (TypeError, ValueError):
            res_id = None
        search = values.get('search') or ''
        if not isinstance(search, str):
            raise ValueError(_('Invalid shared tab'))
        title = values.get('title') or model_name
        if not isinstance(title, str):
            title = model_name

        for existing in list(self.interface.tabs):
            if (existing.get('kind') == 'wizard'
                    and not existing.get('ended')):
                Wizard = self.pool.get(
                    existing['wizard_name'], type='wizard')
                Wizard.delete(existing['wizard_session'])
        self.interface.data['tabs'] = []
        self.interface.data['active_tab'] = None
        self.interface.data['startup_actions'] = []
        action = {
            'id': None,
            'name': title,
            'type': 'ir.action.act_window',
            'res_model': model_name,
            'res_id': res_id,
            'views': views,
            'domains': [],
            'pyson_domain': '[]',
            'pyson_context': '{}',
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': limit,
            }
        tab = self.interface.add_tab({
                'kind': 'window',
                'title': title[:500],
                'action_id': None,
                'action': encode_value(action),
                'model': model_name,
                'res_id': res_id,
                'context': encode_value({}),
                'domain': encode_value(domain),
                'context_domain': encode_value(context_domain),
                'domain_tabs': encode_value(domain_tabs),
                'domain_counts': encode_value([]),
                'active_domain': active_domain,
                'search_value': encode_value(search_value),
                'order': encode_value(order),
                'default_order': encode_value(default_order),
                'view_ids': view_ids,
                'view_types': view_types,
                'view_type': view_type,
                'view_id': view_id,
                'limit': limit,
                'offset': 0,
                'search': search[:20000],
                'search_draft': search[:20000],
                'search_domain': encode_value(search_domain),
                'search_filters': encode_value(search_filters),
                'active_only': bool(values.get('active_only', True)),
                'records': {},
                'record_order': [],
                'selected': [],
                'current_record': None,
                'toolbar': {},
                'pages': {},
                'column_visibility': {},
                })
        self.load_tab(tab, ids=[res_id] if res_id else None)
        self.save()
        return tab

    def _open_window(self, action, data, extra_context, reuse=True):
        base_context = self.context(extra_context, data)
        action_context = evaluate(
            action.get('pyson_context'), base_context, {}) or {}
        tab_context = dict(extra_context or {})
        tab_context.update(action_context)
        evaluation_context = self.context(tab_context, data)
        evaluation_context['context'] = evaluation_context

        views = action.get('views') or []
        view_ids = []
        view_types = []
        for view in views:
            view_id, view_type = view
            if view_type in SUPPORTED_VIEWS:
                view_ids.append(view_id)
                view_types.append(view_type)
        if not view_types:
            view_types = ['tree', 'form']
            view_ids = [None, None]
        if action.get('res_id') or data.get('res_id'):
            if 'form' in view_types:
                index = view_types.index('form')
                view_types.insert(0, view_types.pop(index))
                view_ids.insert(0, view_ids.pop(index))

        domain = evaluate(
            action.get('pyson_domain'), evaluation_context, [])
        context_domain = evaluate(
            action.get('context_domain'), evaluation_context, []) or []
        domain_tabs = [
            {
                'name': name,
                'domain': evaluate(
                    tab_domain, evaluation_context, []) or [],
                'count': bool(count),
                }
            for name, tab_domain, count in action.get('domains', [])
            ]
        search_value = evaluate(
            action.get('pyson_search_value'), evaluation_context, [])
        order = evaluate(
            action.get('pyson_order'), evaluation_context, None)
        window = {
                'kind': 'window',
                'title': action.get('name') or action.get('res_model'),
                'action_id': action.get('id'),
                'action': encode_value(action),
                'model': action.get('res_model') or data.get('res_model'),
                'res_id': action.get('res_id') or data.get('res_id'),
                'context': encode_value(tab_context),
                'domain': encode_value(domain),
                'context_domain': encode_value(context_domain),
                'domain_tabs': encode_value(domain_tabs),
                'domain_counts': encode_value([]),
                'active_domain': 0,
                'search_value': encode_value(search_value),
                'order': encode_value(order),
                'default_order': encode_value(order),
                'view_ids': view_ids,
                'view_types': view_types,
                'view_type': view_types[0],
                'view_id': view_ids[0],
                'limit': action.get('limit') or 1000,
                'offset': 0,
                'search': '',
                'search_draft': '',
                'search_domain': [],
                'search_filters': {},
                'active_only': True,
                'records': {},
                'record_order': [],
                'selected': [],
                'current_record': None,
                'toolbar': {},
                'pages': {},
                'column_visibility': {},
                }
        comparison = {
            'model': window['model'],
            'res_id': window['res_id'],
            'context': tab_context,
            'domain': domain,
            'context_domain': context_domain,
            'domain_tabs': domain_tabs,
            'search_value': search_value,
            'view_ids': view_ids,
            'view_types': view_types,
            }
        if reuse:
            for tab in self.interface.tabs:
                if self._same_window(tab, comparison, bool(views)):
                    self.interface.activate(tab['id'])
                    return tab

        tab = self.interface.add_tab(window)
        res_id = window['res_id']
        self.load_tab(tab, ids=[res_id] if res_id else None)
        return tab

    def _open_wizard(self, action, data, extra_context):
        Wizard = self.pool.get(action['wiz_name'], type='wizard')
        context = self.context(extra_context, data)
        context['action_id'] = action.get('id')
        active_tab = self.interface.active_tab
        return_tab = active_tab['id'] if active_tab else None
        if (active_tab
                and active_tab.get('kind') == 'wizard'
                and not active_tab.get('window')):
            return_tab = active_tab.get('return_tab')
        with Transaction().set_context(context):
            session_id, start_state, end_state = Wizard.create()
            result = Wizard.execute(session_id, {}, start_state)
            if not result.get('view'):
                end_action = Wizard.delete(session_id)
                if end_action:
                    result.setdefault('actions', []).append((end_action, {}))
        tab = self.interface.add_tab({
                'kind': 'wizard',
                'title': action.get('name') or action['wiz_name'],
                'action': encode_value(action),
                'wizard_name': action['wiz_name'],
                'wizard_session': session_id,
                'wizard_state': start_state,
                'wizard_end_state': end_state,
                'context': encode_value(extra_context or {}),
                'data': encode_value(data),
                'window': bool(action.get('window')),
                'return_tab': return_tab,
                })
        self._apply_wizard_result(tab, result)
        if tab.get('ended'):
            self._reload_wizard_source(tab)
            self.interface.close(tab['id'])
            return self.interface.get_tab(return_tab)
        return tab

    def _apply_wizard_result(self, tab, result):
        if result.get('view'):
            view = result['view']
            values = dict(view.get('defaults') or {})
            values.update(view.get('values') or {})
            fields_view = view['fields_view']
            Model = self.pool.get(fields_view['model'])
            context = self.context(
                decode_value(tab.get('context', {})),
                decode_value(tab.get('data', {})))
            with Transaction().set_context(context):
                record = Model(**self._record_values(Model, values))
                changed = set(values)
                if changed:
                    record.on_change(changed)
                dependent = self._dependent_fields(fields_view, changed)
                if dependent:
                    record.on_change_with(dependent)
                values.update(record._default_values)
            tab.update({
                    'wizard_state': view['state'],
                    'model': fields_view.get('model'),
                    'view': encode_value(fields_view),
                    'values': encode_value(values),
                    'buttons': encode_value(view.get('buttons') or []),
                    'ended': False,
                    })
        else:
            tab['ended'] = True
        downloads = []
        for action, data in result.get('actions', []):
            if isinstance(action, str):
                return_tab = self.interface.get_tab(tab.get('return_tab'))
                if return_tab and return_tab.get('kind') == 'window':
                    self.client_action(return_tab, action)
                continue
            action = self.action_value(action)
            if action.get('type') == 'ir.action.report':
                downloads.append(self.queue_report(action, data))
            else:
                self.open_action(action, data)
        return downloads

    def _reload_wizard_source(self, wizard_tab):
        source = self.interface.get_tab(wizard_tab.get('return_tab'))
        if not source or source.get('kind') != 'window':
            return
        data = decode_value(wizard_tab.get('data', {}))
        source_model = source.get('model')
        wizard_model = data.get('model')
        if not wizard_model or wizard_model == 'ir.ui.menu':
            return
        if source_model != wizard_model:
            # Sao reloads the current parent when a wizard was launched from
            # one of its children.
            current = source.get('current_record')
            if not current or current not in source.get('records', {}):
                return
        if source.get('res_id') or source.get('relation_modal'):
            ids = [
                source['records'][key].get('id')
                for key in source.get('record_order', [])
                if key in source.get('records', {})
                and source['records'][key].get('id')
                ]
            self.load_tab(source, ids=ids)
        else:
            self.load_tab(source)

    def wizard_step(self, tab_id, button_state, values):
        tab = self._tab(tab_id, kind='wizard')
        startup_action = bool(tab.get('startup_action'))
        Wizard = self.pool.get(tab['wizard_name'], type='wizard')
        data = {
            tab['wizard_state']: decode_value(values),
            }
        context = self.context(
            decode_value(tab.get('context', {})),
            decode_value(tab.get('data', {})))
        with Transaction().set_context(context):
            result = Wizard.execute(
                tab['wizard_session'], data, button_state)
            if not result.get('view'):
                end_action = Wizard.delete(tab['wizard_session'])
                if end_action:
                    result.setdefault('actions', []).append((end_action, {}))
        downloads = self._apply_wizard_result(tab, result)
        if tab.get('ended'):
            self._reload_wizard_source(tab)
            self.interface.close(tab_id)
            if startup_action:
                self._start_next_user_actions()
        self.save()
        return tab, downloads

    def queue_report(self, action, data, extra_context=None):
        key = uuid.uuid4().hex
        downloads = self.interface.data.setdefault('downloads', {})
        downloads[key] = {
            'action': encode_value(action),
            'data': encode_value(data),
            'context': encode_value(extra_context or {}),
            }
        return key

    def download_report(self, key):
        downloads = self.interface.data.setdefault('downloads', {})
        try:
            definition = downloads.pop(key)
        except KeyError:
            raise ValueError(_('This download is no longer available'))
        self.save()
        return self.execute_report(
            decode_value(definition['action']),
            decode_value(definition['data']),
            decode_value(definition['context']))

    def update_wizard_field(self, tab_id, field_name, raw_value):
        tab = self._tab(tab_id, kind='wizard')
        view = decode_value(tab.get('view', {}))
        Model = self.pool.get(view['model'])
        if field_name not in Model._fields:
            raise ValueError(_('Unknown wizard field %s') % field_name)
        definition = view.get('fields', {}).get(field_name, {})
        value = self.parse_value(
            Model._fields[field_name], raw_value, definition)
        values = decode_value(tab.get('values', {}))
        record = Model(**self._record_values(Model, values))
        before = encode_value(record._default_values)
        setattr(record, field_name, value)
        record.on_change({field_name})
        dependent = self._dependent_fields(view, {field_name})
        if dependent:
            record.on_change_with(dependent)
        changed = self._record_changes(record, before)
        values.update(changed)
        tab['values'] = encode_value(values)
        tab['notice'] = encode_value(record.on_change_notify())
        self.save()
        return tab, set(changed) | {field_name}

    def _tab(self, tab_id, kind=None):
        tab = self.interface.get_tab(tab_id)
        if not tab:
            raise KeyError(_('Unknown tab %s') % tab_id)
        if kind and tab.get('kind') != kind:
            raise ValueError(_('Tab %s is not a %s tab') % (tab_id, kind))
        return tab

    def activate_tab(self, tab_id):
        self.interface.activate(tab_id)
        self.save()
        return self._tab(tab_id)

    def close_tab(self, tab_id):
        tab = self.interface.get_tab(tab_id)
        return_tab = (
            tab.get('return_tab')
            if tab and tab.get('relation_modal') else None)
        if tab and tab.get('kind') == 'wizard' and not tab.get('ended'):
            Wizard = self.pool.get(tab['wizard_name'], type='wizard')
            Wizard.delete(tab['wizard_session'])
        self.interface.close(tab_id)
        if return_tab and self.interface.get_tab(return_tab):
            self.interface.activate(return_tab)
        self.save()
        return self.interface.active_tab

    def switch_view(self, tab_id, view_type):
        tab = self._tab(tab_id, kind='window')
        if view_type not in tab['view_types']:
            raise ValueError(_('View %s is not part of this action') % view_type)
        index = tab['view_types'].index(view_type)
        tab['view_type'] = view_type
        tab['view_id'] = tab['view_ids'][index]
        self.load_tab(tab)
        self.save()
        return tab

    def switch_domain(self, tab_id, index):
        tab = self._tab(tab_id, kind='window')
        domains = decode_value(tab.get('domain_tabs', []))
        index = int(index)
        if index < 0 or index >= len(domains):
            raise ValueError(_('Unknown domain tab'))
        tab['active_domain'] = index
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    def switch_page(self, tab_id, notebook, page):
        tab = self._tab(tab_id)
        tab.setdefault('pages', {})[notebook] = int(page)
        self.save()
        return tab

    def open_preferences(self, values):
        self.interface.data['preferences_open'] = True
        state = self.interface.component('preferences')
        if 'values' not in state:
            state['values'] = encode_value(values)
            state['pages'] = {}
            state['changed'] = []
        else:
            state.setdefault('changed', [])
        self.save()
        return state

    def close_preferences(self):
        self.interface.data['preferences_open'] = False
        self.interface.data['components'].pop('preferences', None)
        self.save()

    def update_preference(self, view, field_name, raw_value):
        User = self.pool.get('res.user')
        if field_name not in User._fields:
            raise ValueError(_('Unknown preference field %s') % field_name)
        state = self.interface.component('preferences')
        values = decode_value(state.get('values', {}))
        definition = view.get('fields', {}).get(field_name, {})
        if definition.get('type') != User._fields[field_name]._type:
            value = raw_value
            if definition.get('type') == 'selection':
                for key, label in definition.get('selection', []):
                    if str(key) == str(raw_value):
                        value = key
                        break
            values[field_name] = value
            state['values'] = encode_value(values)
            state['changed'] = sorted(
                set(state.get('changed', [])) | {field_name})
            self.save()
            return state, {field_name}
        value = self.parse_value(
            User._fields[field_name], raw_value, definition)
        record_values = self._record_values(User, values)
        for name in list(record_values):
            if (view.get('fields', {}).get(name, {}).get('type')
                    != User._fields[name]._type):
                # The preferences view deliberately exposes fields such as
                # language and action as selections instead of their model
                # field type. Those client values are not suitable for
                # instantiating an in-memory res.user record.
                record_values.pop(name)
        record = User(
            Transaction().user,
            **record_values)
        before = encode_value(record._default_values)
        setattr(record, field_name, value)
        record.on_change({field_name})
        dependent = self._dependent_fields(view, {field_name})
        if dependent:
            record.on_change_with(dependent)
        changed = self._record_changes(record, before)
        values.update(changed)
        state['values'] = encode_value(values)
        changed_fields = set(changed) | {field_name}
        state['changed'] = sorted(
            set(state.get('changed', [])) | changed_fields)
        self.save()
        return state, changed_fields

    def _update_window_counts(
            self, tab, Model, view, refresh_count=True, exact=False):
        base_domain = combine_domains(
            decode_value(tab.get('domain', [])),
            decode_value(tab.get('context_domain', [])),
            decode_value(tab.get('search_value', [])),
            decode_value(tab.get('search_domain', [])))
        if tab.get('search') and not decode_value(
                tab.get('search_domain', [])):
            base_domain = combine_domains(
                base_domain, self._search_domain(tab, view))
        domain_tabs = decode_value(tab.get('domain_tabs', []))
        active_domain = []
        active_domain_index = 0
        if domain_tabs:
            active_domain_index = min(
                tab.get('active_domain', 0), len(domain_tabs) - 1)
            active_domain = domain_tabs[active_domain_index]['domain']
        domain = combine_domains(base_domain, active_domain)
        if refresh_count:
            offset = int(tab.get('offset') or 0)
            if exact:
                tab['count'] = Model.search_count(domain)
                tab['count_limited'] = False
            else:
                count = Model.search_count(
                    domain, offset=offset, limit=RECORD_COUNT_LIMIT + 1)
                tab['count'] = offset + count
                tab['count_limited'] = count > RECORD_COUNT_LIMIT
            tab['count_exact'] = not tab['count_limited']
            tab['domain_counts'] = encode_value([
                    (
                        min(tab['count'], RECORD_COUNT_LIMIT)
                        if index == active_domain_index
                        else Model.search_count(
                            combine_domains(
                                base_domain, domain_tab['domain']),
                            limit=RECORD_COUNT_LIMIT)
                    ) if domain_tab.get('count') else None
                    for index, domain_tab in enumerate(domain_tabs)
                    ])
        return domain

    def load_tab(
            self, tab, ids=None, append=False, refresh_count=True):
        Model = self.pool.get(tab['model'])
        ModelAccess = self.pool.get('ir.model.access')
        tab['history'] = bool(getattr(Model, '_history', False))
        tab['access'] = ModelAccess.get_access(
            [tab['model']])[tab['model']]
        context = self.context(decode_value(tab.get('context', {})))
        tab['search_context'] = encode_value(context)
        if not tab.get('active_only', True):
            context['active_test'] = False
        screen_width = self.interface.data.get('screen_width')
        if screen_width:
            context.update({
                    'screen_size': (int(screen_width), 0),
                    'view_tree_width': True,
                    })
        with Transaction().set_context(context):
            view = Model.fields_view_get(
                view_id=tab.get('view_id'),
                view_type=tab['view_type'])
            tab['view'] = encode_value(view)
            tab['toolbar'] = encode_value(Model.view_toolbar_get())
            fields_names = list(view.get('fields', {}).keys())
            if tab['view_type'] == 'tree':
                read_fields = WidgetRenderer.tree_read_fields(view, Model)
            else:
                read_fields = [
                    name for name in fields_names
                    if name in Model._fields and name != 'id'
                    ]
            root = ElementTree.fromstring(view.get('arch') or '<form/>')
            for node in root.iter('field'):
                definition = view.get('fields', {}).get(
                    node.attrib.get('name'), {})
                for dependent in (
                        node.attrib.get('filename'),
                        definition.get('filename'),
                        node.attrib.get('symbol'),
                        definition.get('symbol')):
                    if dependent in Model._fields and dependent not in read_fields:
                        read_fields.append(dependent)
            if 'rec_name' not in read_fields:
                read_fields.append('rec_name')

            domain = self._update_window_counts(
                tab, Model, view,
                refresh_count=refresh_count and not append)

            search_offset = int(tab.get('offset') or 0)
            record_limit = int(tab.get('limit') or 1000)
            hierarchy_limit = record_limit
            if tab.get('view_type') == 'tree':
                if append:
                    search_offset = int(
                        tab.get('tree_next_offset') or search_offset)
                    tree_end_offset = min(
                        int(tab.get('tree_end_offset') or 0),
                        int(tab.get('count') or 0))
                else:
                    tree_end_offset = min(
                        search_offset + record_limit,
                        int(tab.get('count') or 0))
                tab['tree_end_offset'] = tree_end_offset
                record_limit = min(
                    TREE_RECORD_CHUNK_SIZE,
                    max(0, tree_end_offset - search_offset))
                hierarchy_limit = TREE_RECORD_CHUNK_SIZE
            if ids is None:
                ids = (
                    Model.search(
                        domain,
                        offset=search_offset,
                        limit=record_limit,
                        order=decode_value(tab.get('order')))
                    if record_limit else [])
            else:
                ids = [int(id_) for id_ in ids if id_]
                order = decode_value(tab.get('order'))
                if len(ids) > 1 and order:
                    ids = Model.search([
                            ('id', 'in', ids),
                            ], order=order)
            ids = [int(id_) for id_ in ids if id_]
            if tab.get('view_type') == 'tree':
                tab['tree_next_offset'] = (
                    search_offset + len(ids)
                    if ids else int(tab.get('count') or 0))
            binary_context = {
                '%s.%s' % (Model.__name__, name): 'size'
                for name in read_fields
                if name in Model._fields
                and Model._fields[name]._type == 'binary'
                }
            with Transaction().set_context(binary_context):
                values = Model.read(ids, read_fields) if ids else []
                if values:
                    by_id = {
                        row['id']: row for row in values}
                    values = [
                        by_id[record_id]
                        for record_id in ids if record_id in by_id
                        ]
                child_field = view.get('field_childs')
                if child_field in read_fields:
                    known = {row['id'] for row in values}
                    pending = {
                        child_id
                        for row in values
                        for child_id in row.get(child_field, [])
                        if child_id not in known
                        }
                    while pending and len(known) < hierarchy_limit:
                        child_ids = list(pending)[
                            :hierarchy_limit - len(known)]
                        child_values = Model.read(child_ids, read_fields)
                        values.extend(child_values)
                        known.update(child_ids)
                        pending = {
                            child_id
                            for row in child_values
                            for child_id in row.get(child_field, [])
                            if child_id not in known
                            }

        old_records = tab.get('records', {})
        records = dict(old_records) if append else {}
        order = list(tab.get('record_order', [])) if append else []
        for row in values:
            key = str(row['id'])
            old = old_records.get(key)
            if old and old.get('dirty'):
                records[key] = old
            else:
                records[key] = {
                    'key': key,
                    'id': row['id'],
                    'values': encode_value(row),
                    'baseline': encode_value(row),
                    'dirty': [],
                    'new': False,
                    'deleted': False,
                    }
            if key not in order:
                order.append(key)

        if not append:
            for key, record in old_records.items():
                if record.get('new') and key not in records:
                    records[key] = record
                    order.insert(0, key)
        tab['records'] = records
        tab['record_order'] = order
        tab['selected'] = [
            key for key in tab.get('selected', []) if key in records]
        if tab.get('current_record') not in records:
            tab['current_record'] = (
                order[0]
                if tab.get('view_type') != 'tree' and order else None)
        tab['dirty'] = any(record.get('dirty') for record in records.values())
        return tab

    def load_tree_records(self, tab_id):
        """Load the next visible chunk of a window tree."""
        tab = self._tab(tab_id, kind='window')
        if tab.get('view_type') != 'tree':
            raise ValueError(_('This tab is not a tree view'))
        previous_keys = set(tab.get('record_order', []))
        if int(tab.get('tree_next_offset') or 0) < int(
                tab.get('tree_end_offset') or 0):
            self.load_tab(tab, append=True)
        loaded_keys = [
            key for key in tab.get('record_order', [])
            if key not in previous_keys]
        self.save()
        return tab, loaded_keys

    def count_records(self, tab_id):
        """Compute the unrestricted count for the current window domain."""
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        context = self.context(decode_value(tab.get('context', {})))
        if not tab.get('active_only', True):
            context['active_test'] = False
        with Transaction().set_context(context):
            view = decode_value(tab.get('view', {}))
            self._update_window_counts(
                tab, Model, view, exact=True)
        self.save()
        return tab

    def revisions(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        if not getattr(Model, '_history', False):
            raise ValueError(_('This model does not keep revisions'))
        keys = tab.get('selected') or [tab.get('current_record')]
        ids = [
            tab['records'][key]['id']
            for key in keys
            if key in tab['records'] and tab['records'][key].get('id')
            ]
        if not ids:
            raise ValueError(_('Select a saved record first'))
        tab['revisions'] = encode_value(Model.history_revisions(ids))
        tab['revision_open'] = True
        self.save()
        return tab

    def close_revisions(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        tab['revision_open'] = False
        self.save()
        return tab

    def set_revision(self, tab_id, index=None):
        tab = self._tab(tab_id, kind='window')
        context = decode_value(tab.get('context', {}))
        if index is None:
            context.pop('_datetime', None)
        else:
            revisions = decode_value(tab.get('revisions', []))
            index = int(index)
            if index < 0 or index >= len(revisions):
                raise ValueError(_('Unknown revision'))
            context['_datetime'] = revisions[index][0] + timedelta(
                milliseconds=1)
        tab['context'] = encode_value(context)
        tab['revision_open'] = False
        self.load_tab(tab)
        self.save()
        return tab

    def reload_tab(self, tab_id):
        tab = self._tab(tab_id)
        if tab.get('kind') == 'dashboard':
            self._load_dashboard(tab)
        elif tab.get('kind') == 'window':
            self.load_tab(tab)
        else:
            raise ValueError(_('This tab can not be reloaded'))
        self.save()
        return tab

    def search(self, tab_id, text):
        tab = self._tab(tab_id, kind='window')
        tab['search_bookmark'] = None
        tab['search'] = text or ''
        tab['search_draft'] = tab['search']
        tab['search_filters'] = {}
        view = decode_value(tab.get('view', {}))
        tab['search_domain'] = encode_value(
            self._search_domain(tab, view))
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    def update_search_draft(self, tab_id, text):
        tab = self._tab(tab_id, kind='window')
        tab['search_draft'] = text or ''
        self.save()
        return tab

    def advanced_search(self, tab_id, filters):
        tab = self._tab(tab_id, kind='window')
        tab['search_bookmark'] = None
        view = decode_value(tab.get('view', {}))
        definitions = search_field_definitions(view)
        domain = []
        search_filters = {}
        labels = []
        for name, values in filters.items():
            if name not in definitions:
                continue
            definition = definitions[name]
            title = definition.get('string') or name
            cleaned = {
                mode: str(value).strip()
                for mode, value in values.items()
                if str(value).strip()
                }
            if not cleaned:
                continue
            search_filters[name] = cleaned
            if cleaned.get('value'):
                raw_value = cleaned['value']
                domain.extend(self._search_leaf(
                        name, definition, raw_value))
                labels.append('%s: %s' % (title, raw_value))
            if cleaned.get('from'):
                raw_value = cleaned['from']
                domain.extend(self._search_leaf(
                        name, definition, raw_value, '>='))
                labels.append('%s: >=%s' % (title, raw_value))
            if cleaned.get('to'):
                raw_value = cleaned['to']
                domain.extend(self._search_leaf(
                        name, definition, raw_value, '<='))
                labels.append('%s: <=%s' % (title, raw_value))
        tab['search'] = ' '.join(labels)
        tab['search_draft'] = tab['search']
        tab['search_domain'] = encode_value(domain)
        tab['search_filters'] = encode_value(search_filters)
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    def search_bookmarks(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        ViewSearch = self.pool.get('ir.ui.view_search')
        return ViewSearch.get().get(tab['model'], [])

    def current_search_bookmark(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        current = decode_value(tab.get('search_domain', []))
        for bookmark in self.search_bookmarks(tab_id):
            if (PYSONEncoder().encode(bookmark[2])
                    == PYSONEncoder().encode(current)):
                return bookmark
        return None

    def add_search_bookmark(self, tab_id, name):
        tab = self._tab(tab_id, kind='window')
        domain = decode_value(tab.get('search_domain', []))
        if not name or not domain:
            raise ValueError(_('A bookmark name and search are required'))
        ViewSearch = self.pool.get('ir.ui.view_search')
        bookmark_id = ViewSearch.set(
            name.strip(), tab['model'], PYSONEncoder().encode(domain))
        tab['search_bookmark'] = bookmark_id
        self.save()
        return tab

    def remove_search_bookmark(self, tab_id, bookmark_id):
        tab = self._tab(tab_id, kind='window')
        bookmarks = self.search_bookmarks(tab_id)
        if not any(
                int(bookmark[0]) == int(bookmark_id)
                and bookmark[3]
                for bookmark in bookmarks):
            raise ValueError(_('This search bookmark can not be removed'))
        ViewSearch = self.pool.get('ir.ui.view_search')
        ViewSearch.unset(int(bookmark_id))
        if int(tab.get('search_bookmark') or 0) == int(bookmark_id):
            tab['search_bookmark'] = None
        self.save()
        return tab

    def apply_search_bookmark(self, tab_id, bookmark_id):
        tab = self._tab(tab_id, kind='window')
        bookmark = next((
                bookmark for bookmark in self.search_bookmarks(tab_id)
                if int(bookmark[0]) == int(bookmark_id)), None)
        if not bookmark:
            raise ValueError(_('Unknown search bookmark'))
        domain = bookmark[2]
        view = decode_value(tab.get('view', {}))
        tab['search'] = self.search_domain_text(tab, view, domain)
        tab['search_draft'] = tab['search']
        tab['search_domain'] = encode_value(domain)
        tab['search_filters'] = {}
        tab['search_bookmark'] = int(bookmark_id)
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    @staticmethod
    def search_domain_text(tab, view, domain):
        return search_domain_parser(tab, view).string(domain)

    def toggle_active(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        tab['active_only'] = not tab.get('active_only', True)
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    def select_neighbor(self, tab_id, direction):
        tab = self._tab(tab_id, kind='window')
        order = tab.get('record_order', [])
        if not order:
            return tab
        current = tab.get('current_record')
        index = order.index(current) if current in order else 0
        if direction == 'previous':
            index = max(0, index - 1)
        elif direction == 'next':
            index = min(len(order) - 1, index + 1)
        else:
            raise ValueError(_('Unknown record direction'))
        tab['current_record'] = order[index]
        tab['selected'] = [order[index]]
        if tab.get('relation_navigation'):
            Model = self.pool.get(tab['model'])
            record_id = int(order[index])
            tab['res_id'] = record_id
            tab['title'] = Model(record_id).rec_name
        self.save()
        return tab

    def page(self, tab_id, direction):
        tab = self._tab(tab_id, kind='window')
        limit = int(tab.get('limit') or 1000)
        offset = int(tab.get('offset') or 0)
        if direction == 'next':
            if tab.get('count_limited'):
                offset += limit
            else:
                offset = min(
                    offset + limit,
                    max(0, int(tab.get('count') or 0) - 1))
        elif direction == 'previous':
            offset = max(0, offset - limit)
        else:
            raise ValueError(_('Unknown page direction'))
        tab['offset'] = offset
        self.load_tab(
            tab, refresh_count=not tab.get('count_exact', False))
        self.save()
        return tab

    def sort(self, tab_id, field_name):
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(view.get('arch') or '<form/>')
        definition = view.get('fields', {}).get(field_name)
        if (field_name not in Model._fields
                or definition is None
                or definition.get('sortable') is False
                or not Model._fields[field_name].sortable(Model)
                or root.tag != 'tree'
                or root.attrib.get('sequence')
                or view.get('field_childs')):
            raise ValueError(_('Unknown sort field'))
        if 'default_order' not in tab:
            tab['default_order'] = tab.get('order')
        default_order = decode_value(tab.get('default_order'))
        order = decode_value(tab.get('order')) or []
        current_direction = None
        if (len(order) == 1
                and isinstance(order[0], (list, tuple))
                and len(order[0]) >= 2
                and order[0][0] == field_name):
            current_direction = str(
                order[0][1]).strip().split(' ', 1)[0].upper()
        if current_direction == 'ASC':
            order = [(field_name, 'DESC')]
        elif current_direction == 'DESC':
            order = default_order
        else:
            order = [(field_name, 'ASC')]
        tab['order'] = encode_value(order)
        tab['offset'] = 0
        self.load_tab(tab)
        self.save()
        return tab

    def toggle_column(self, tab_id, field_name, visible):
        tab = self._tab(tab_id, kind='window')
        view = decode_value(tab.get('view', {}))
        if field_name not in view.get('fields', {}):
            raise ValueError(_('Unknown optional column'))
        tab.setdefault('column_visibility', {})[field_name] = bool(visible)
        self.save()
        return tab

    def toggle_tree_node(self, tab_id, record_key):
        tab = self._tab(tab_id, kind='window')
        if record_key not in tab.get('records', {}):
            raise ValueError(_('Unknown tree node'))
        expanded = tab.setdefault('expanded', [])
        if record_key in expanded:
            expanded.remove(record_key)
        else:
            expanded.append(record_key)
        self.save()
        return tab

    def move_tree_record(
            self, tab_id, record_key, target_key, position):
        tab = self._tab(tab_id, kind='window')
        order = tab.get('record_order', [])
        if record_key not in order or target_key not in order:
            raise ValueError(_('Unknown tree record'))
        if position not in {'before', 'after', 'inside'}:
            raise ValueError(_('Unknown tree drop position'))
        if record_key == target_key:
            return tab
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(view.get('arch') or '<tree/>')
        sequence = root.attrib.get('sequence')
        Model = self.pool.get(tab['model'])
        if not sequence or sequence not in Model._fields:
            raise ValueError(_('This tree can not be reordered'))
        if (
                not tab.get('access', {}).get('write', True)
                or decode_value(tab.get('context', {})).get('_datetime')):
            raise ValueError(_('This tree is read-only'))

        child_field = view.get('field_childs')
        children = {}
        parent_by_child = {}
        roots = list(order)
        if child_field:
            for key in order:
                child_keys = [
                    str(record_id)
                    for record_id in decode_value(
                        tab['records'][key].get('values', {})).get(
                            child_field, [])
                    if str(record_id) in tab['records']
                    ]
                children[key] = child_keys
                parent_by_child.update({
                        child_key: key for child_key in child_keys})
            roots = [
                key for key in order if key not in parent_by_child]

        source_parent = parent_by_child.get(record_key)
        source_siblings = (
            children[source_parent] if source_parent else roots)
        target_parent = parent_by_child.get(target_key)
        if position == 'inside':
            if not child_field:
                raise ValueError(
                    _('A flat tree can not contain child records'))
            destination_parent = target_key
            destination_siblings = children[target_key]
            destination_index = len(destination_siblings)
        else:
            destination_parent = target_parent
            destination_siblings = (
                children[target_parent] if target_parent else roots)
            destination_index = destination_siblings.index(target_key)
            if position == 'after':
                destination_index += 1

        ancestor = destination_parent
        while ancestor:
            if ancestor == record_key:
                raise ValueError(
                    _('A tree record can not contain itself'))
            ancestor = parent_by_child.get(ancestor)

        source_index = source_siblings.index(record_key)
        source_siblings.pop(source_index)
        if (
                source_siblings is destination_siblings
                and source_index < destination_index):
            destination_index -= 1
        destination_siblings.insert(destination_index, record_key)

        if child_field:
            for parent_key in {source_parent, destination_parent} - {None}:
                values = decode_value(
                    tab['records'][parent_key].get('values', {}))
                values[child_field] = [
                    tab['records'][key].get('id') or key
                    for key in children[parent_key]]
                tab['records'][parent_key]['values'] = encode_value(values)
            if source_parent != destination_parent:
                relation_field = getattr(
                    Model._fields.get(child_field), 'field', None)
                if relation_field and relation_field in Model._fields:
                    record = tab['records'][record_key]
                    values = decode_value(record.get('values', {}))
                    values[relation_field] = (
                        tab['records'][destination_parent].get('id')
                        if destination_parent else None)
                    record['values'] = encode_value(values)
                    record['dirty'] = sorted(
                        set(record.get('dirty', [])) | {relation_field})

            reordered = []
            visited = set()

            def append_record(key):
                if key in visited:
                    return
                visited.add(key)
                reordered.append(key)
                for child_key in children.get(key, []):
                    append_record(child_key)

            for key in roots:
                append_record(key)
            for key in order:
                append_record(key)
            order[:] = reordered
        else:
            order[:] = roots

        sequence_groups = [source_siblings]
        if destination_siblings is not source_siblings:
            sequence_groups.append(destination_siblings)
        for siblings in sequence_groups:
            for index, key in enumerate(siblings, 1):
                record = tab['records'][key]
                values = decode_value(record.get('values', {}))
                values[sequence] = index * 10
                record['values'] = encode_value(values)
                record['dirty'] = sorted(
                    set(record.get('dirty', [])) | {sequence})
        tab['dirty'] = True
        tab['current_record'] = record_key
        tab['selected'] = [record_key]
        self.save()
        return tab

    def navigate_calendar(self, tab_id, direction):
        tab = self._tab(tab_id, kind='window')
        current = date.fromisoformat(
            tab.get('calendar_date') or date.today().isoformat())
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(
            view.get('arch') or '<calendar/>')
        mode = tab.get(
            'calendar_mode', root.attrib.get('mode', 'month'))
        if direction == 'today':
            current = date.today()
        elif direction == 'previous':
            if mode == 'day':
                current -= timedelta(days=1)
            elif mode == 'week':
                current -= timedelta(days=7)
            else:
                current = (
                    current.replace(
                        year=current.year - 1, month=12, day=1)
                    if current.month == 1
                    else current.replace(month=current.month - 1, day=1))
        elif direction == 'next':
            if mode == 'day':
                current += timedelta(days=1)
            elif mode == 'week':
                current += timedelta(days=7)
            else:
                current = (
                    current.replace(
                        year=current.year + 1, month=1, day=1)
                    if current.month == 12
                    else current.replace(month=current.month + 1, day=1))
        else:
            raise ValueError(_('Unknown calendar direction'))
        tab['calendar_date'] = current.isoformat()
        self.save()
        return tab

    def set_calendar_mode(self, tab_id, mode):
        tab = self._tab(tab_id, kind='window')
        if mode not in {'day', 'week', 'month'}:
            raise ValueError(_('Unknown calendar mode'))
        tab['calendar_mode'] = mode
        self.save()
        return tab

    def move_calendar_record(self, tab_id, record_key, direction):
        tab = self._tab(tab_id, kind='window')
        record = tab.get('records', {}).get(record_key)
        if not record:
            raise ValueError(_('Unknown calendar record'))
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(
            view.get('arch') or '<calendar/>')
        delta = timedelta(days=1 if direction == 'next' else -1)
        if direction not in {'next', 'previous'}:
            raise ValueError(_('Unknown calendar direction'))
        values = decode_value(record.get('values', {}))
        changed = set()
        for name in filter(None, [
                    root.attrib.get('dtstart'),
                    root.attrib.get('dtend')]):
            if values.get(name):
                values[name] += delta
                changed.add(name)
        record['values'] = encode_value(values)
        record['dirty'] = sorted(
            set(record.get('dirty', [])) | changed)
        tab['dirty'] = bool(changed) or tab.get('dirty', False)
        self.save()
        return tab

    def select_record(
            self, tab_id, record_key, selected=None,
            selection=None, current=None):
        tab = self._tab(tab_id, kind='window')
        if record_key not in tab['records']:
            raise KeyError(_('Unknown record %s') % record_key)
        if selection is not None:
            if any(key not in tab['records'] for key in selection):
                raise KeyError(_('Unknown record %s') % record_key)
            selection = list(dict.fromkeys(selection))
            tab['selected'] = selection
            tab['current_record'] = (
                current if current in tab['records'] else
                selection[0] if selection else None)
        else:
            tab['current_record'] = record_key
            selected_keys = tab.setdefault('selected', [])
            if selected is None:
                tab['selected'] = [record_key]
            elif selected is True and record_key not in selected_keys:
                selected_keys.append(record_key)
            elif selected is False and record_key in selected_keys:
                selected_keys.remove(record_key)
        self.save()
        return tab['records'][record_key]

    def select_all(self, tab_id, selected):
        tab = self._tab(tab_id, kind='window')
        tab['selected'] = (
            list(tab.get('record_order', [])) if selected else [])
        if selected and tab['selected']:
            tab['current_record'] = tab['selected'][0]
        self.save()
        return tab

    def _search_domain(self, tab, view):
        text = (tab.get('search') or '').strip()
        if not text:
            return []
        return search_domain_parser(tab, view).parse(text)

    @staticmethod
    def _search_leaf(name, definition, raw_value, operator='='):
        type_ = definition.get('type')
        value = raw_value
        if type_ in {'char', 'text'} and operator == '=':
            operator = 'ilike'
            value = '%%%s%%' % raw_value
        elif type_ in {'many2one', 'one2one'}:
            name += '.rec_name'
            if operator == '=':
                operator = 'ilike'
                value = '%%%s%%' % raw_value
        elif type_ == 'boolean':
            value = raw_value.casefold() in {
                '1', 'true', 'yes', 'y', 'sí', 'si'}
        elif type_ in {'integer', 'bigint'}:
            try:
                value = int(raw_value)
            except ValueError:
                return [('id', '=', None)]
        elif type_ in {'float', 'numeric'}:
            try:
                value = Decimal(raw_value)
            except InvalidOperation:
                return [('id', '=', None)]
        elif type_ == 'date':
            try:
                value = date.fromisoformat(raw_value)
            except ValueError:
                return [('id', '=', None)]
        elif type_ in {'datetime', 'timestamp'}:
            try:
                value = datetime.fromisoformat(raw_value)
            except ValueError:
                return [('id', '=', None)]
            zone = Transaction().context.get('timezone')
            if zone and value.tzinfo is None:
                value = value.replace(
                    tzinfo=timezone.get_tzinfo(zone)).astimezone(
                        timezone.UTC).replace(tzinfo=None)
        elif type_ == 'time':
            try:
                value = time.fromisoformat(raw_value)
            except ValueError:
                return [('id', '=', None)]
        elif type_ in {'selection', 'multiselection'}:
            selection = definition.get('selection') or []
            if isinstance(selection, (list, tuple)):
                for entry in selection:
                    if (not isinstance(entry, (list, tuple))
                            or len(entry) != 2):
                        continue
                    key, title = entry
                    if (str(title).casefold() == raw_value.casefold()
                            or str(key) == raw_value):
                        value = key
                        break
        return [(name, operator, value)]

    def new_record(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        context = self.context(decode_value(tab.get('context', {})))
        if not tab.get('active_only', True):
            context['active_test'] = False
        current_view = decode_value(tab.get('view', {}))
        current_root = ElementTree.fromstring(
            current_view.get('arch') or '<tree/>')
        editable_tree = (
            tab.get('view_type') == 'tree'
            and current_root.attrib.get('editable')
            in {'1', 'top', 'bottom'})
        if ('form' in tab['view_types']
                and tab['view_type'] != 'form'
                and not editable_tree):
            index = tab['view_types'].index('form')
            tab['view_type'] = 'form'
            tab['view_id'] = tab['view_ids'][index]
            with Transaction().set_context(context):
                tab['view'] = encode_value(Model.fields_view_get(
                        view_id=tab['view_id'], view_type='form'))
        view = decode_value(tab['view'])
        field_names = [
            name for name in view.get('fields', {})
            if name in Model._fields
            ]
        with Transaction().set_context(context):
            values = Model.default_get(field_names)
            for name in field_names:
                default_name = 'default_' + name
                if default_name in context:
                    values[name] = context[default_name]
            record_values = self._record_values(Model, values)
            parent_field, parent_record = self._relation_draft_parent(tab)
            if parent_field and parent_record:
                record_values[parent_field] = parent_record
                values[parent_field] = parent_record
            record = Model(**record_values)
            changed = set(values)
            if changed:
                record.on_change(changed)
            dependent = self._dependent_fields(view, changed)
            if dependent:
                record.on_change_with(dependent)
            values.update(record._default_values)
            if parent_field:
                values[parent_field] = None

        key = 'new-%s' % uuid.uuid4().hex
        tab['records'][key] = {
            'key': key,
            'id': None,
            'values': encode_value(values),
            'baseline': {},
            'dirty': sorted(values),
            'new': True,
            'deleted': False,
            }
        tab['record_order'].insert(0, key)
        tab['current_record'] = key
        tab['selected'] = [key]
        tab['dirty'] = True
        self.save()
        return tab['records'][key]

    def _relation_draft_parent(self, tab):
        if not tab.get('relation_draft'):
            return None, None
        origin = tab.get('relation_origin') or {}
        parent = self.interface.get_tab(origin.get('tab'))
        if not parent or parent.get('kind') != 'window':
            return None, None
        stored = parent.get('records', {}).get(origin.get('record'))
        if not stored:
            return None, None
        Parent = self.pool.get(parent['model'])
        values = decode_value(stored.get('values', {}))
        record = Parent(
            stored.get('id'), **self._record_values(Parent, values))
        return tab.get('relation_parent_field'), record

    def _record_values(self, Model, values):
        result = {}
        for name, value in values.items():
            if (name == 'id' or name not in Model._fields
                    or name.endswith('.')):
                continue
            value = decode_value(value)
            field = Model._fields[name]
            if (field._type in {'many2one', 'one2one'}
                    and isinstance(value, (list, tuple))):
                value = value[0] if value else None
            elif field._type in {'one2many', 'many2many'}:
                relation_value = []
                for item in (value or []):
                    if not isinstance(item, dict):
                        relation_value.append(item)
                        continue
                    if item.get('id') and item.get('values'):
                        item = dict(
                            {'id': item['id']},
                            **decode_value(item['values']))
                    else:
                        item = decode_value(item)
                    item.pop('__key__', None)
                    relation_value.append(item)
                value = relation_value
            result[name] = value
        return result

    def _record_changes(self, record, before):
        changes = {}
        for name, value in record._default_values.items():
            if name not in before or encode_value(value) != before[name]:
                changes[name] = value
        return changes

    def _dependent_fields(self, view, changed):
        immediate = []
        later = []
        for name, definition in view.get('fields', {}).items():
            dependencies = set(definition.get('on_change_with') or [])
            if dependencies & set(changed):
                immediate.append(name)
        immediate_set = set(immediate)
        for name in immediate:
            dependencies = set(
                view['fields'][name].get('on_change_with') or [])
            if dependencies & immediate_set:
                later.append(name)
        return [
            name for name in immediate if name not in later
            ] + later

    def parse_value(self, field, value, definition=None):
        definition = definition or {}
        if field._type == 'boolean':
            return str(value).lower() in {'1', 'true', 'on', 'yes'}
        if value == '':
            if field._type in {'char', 'text'}:
                return ''
            return None
        if field._type == 'integer':
            result = int(value)
            return int(result * float(definition.get('factor', 1) or 1))
        if field._type == 'float':
            return (
                float(value)
                * float(definition.get('factor', 1) or 1))
        if field._type == 'numeric':
            try:
                return (
                    Decimal(value)
                    * Decimal(str(definition.get('factor', 1) or 1)))
            except InvalidOperation as exception:
                raise ValueError(_('Invalid decimal value')) from exception
        if field._type in {'date', 'datetime', 'timestamp', 'time'}:
            context = self.context()
            if field._type == 'date':
                if isinstance(value, datetime):
                    return value.date()
                if isinstance(value, date):
                    return value
                return parse_date(value, date_format(context)).date()
            if field._type == 'time':
                if isinstance(value, time):
                    return value
                return parse_date(value, time_format(definition)).time()
            if isinstance(value, datetime):
                return to_server_datetime(value, context)
            value = parse_date(
                value,
                '%s %s' % (
                    date_format(context), time_format(definition)))
            return to_server_datetime(value, context)
        if field._type == 'timedelta':
            return timedelta(seconds=float(value))
        if field._type in {'many2one', 'one2one'}:
            return int(value) if value else None
        if field._type in {'one2many', 'many2many', 'multiselection'}:
            if not isinstance(value, (list, tuple)):
                value = value.split(',') if value else []
            result = []
            for item in value:
                if isinstance(item, dict):
                    result.append(item)
                    continue
                item = str(item).strip()
                if item:
                    result.append(
                        int(item) if item.lstrip('-').isdigit() else item)
            if field._type == 'multiselection':
                selection = definition.get('selection') or []
                if not isinstance(selection, str):
                    choices = {
                        str(key): key for key, label in selection}
                    result = [choices.get(str(item), item) for item in result]
            return result
        if field._type == 'selection':
            selection = definition.get('selection') or []
            if not isinstance(selection, str):
                for key, label in selection:
                    if str(key) == str(value):
                        return key
        if field._type == 'binary' and (
                value is None or value == ''):
            return None
        if field._type == 'dict':
            return json.loads(value or '{}')
        return value

    def update_field(
            self, tab_id, record_key, field_name, raw_value,
            attributes=None):
        tab = self._tab(tab_id, kind='window')
        stored = tab['records'].get(record_key)
        if not stored:
            raise KeyError(_('Unknown record %s') % record_key)
        Model = self.pool.get(tab['model'])
        if field_name not in Model._fields:
            raise KeyError(_('Unknown field %s') % field_name)
        field = Model._fields[field_name]
        view = decode_value(tab['view'])
        definition = dict(
            view.get('fields', {}).get(field_name, {}))
        definition.update(attributes or {})
        value = self.parse_value(field, raw_value, definition)
        values = decode_value(stored['values'])
        record_values = self._record_values(Model, values)
        parent_field, parent_record = self._relation_draft_parent(tab)
        if parent_field and parent_record:
            record_values[parent_field] = parent_record
        record = Model(stored.get('id'), **record_values)
        before = encode_value(record._default_values)
        setattr(record, field_name, value)
        record.on_change({field_name})
        dependent = self._dependent_fields(view, {field_name})
        if dependent:
            record.on_change_with(dependent)
        changed_values = self._record_changes(record, before)
        if parent_field:
            changed_values.pop(parent_field, None)
        values.update(changed_values)
        stored['values'] = encode_value(values)
        dirty = set(stored.get('dirty', []))
        dirty.update(changed_values)
        dirty.add(field_name)
        stored['dirty'] = sorted(dirty)
        tab['dirty'] = True
        tab['current_record'] = record_key
        tab['notice'] = encode_value(record.on_change_notify())
        self.save()
        return stored, set(changed_values) | {field_name}

    def update_binary(
            self, tab_id, record_key, field_name, data,
            filename_field=None, filename=None):
        tab = self._tab(tab_id, kind='window')
        stored = tab['records'][record_key]
        values = decode_value(stored['values'])
        values[field_name] = data
        changed = {field_name}
        if filename_field:
            values[filename_field] = filename if data is not None else None
            changed.add(filename_field)
        stored['values'] = encode_value(values)
        stored['dirty'] = sorted(
            set(stored.get('dirty', [])) | changed)
        tab['dirty'] = True
        tab['current_record'] = record_key
        self.save()
        return stored, changed

    def scan_code(self, tab_id, record_key, code):
        tab = self._tab(tab_id, kind='window')
        stored = tab.get('records', {}).get(record_key)
        if not stored:
            raise ValueError(_('Select a record before scanning'))
        Model = self.pool.get(tab['model'])
        values = decode_value(stored.get('values', {}))
        record = Model(
            stored.get('id'),
            **self._record_values(Model, values))
        before = encode_value(record._default_values)
        record.on_scan_code(code)
        changes = self._record_changes(record, before)
        values.update(changes)
        stored['values'] = encode_value(values)
        stored['dirty'] = sorted(
            set(stored.get('dirty', [])) | set(changes))
        tab['dirty'] = bool(stored['dirty']) or tab.get('dirty', False)
        tab['notice'] = encode_value(record.on_change_notify())
        self.save()
        return tab

    def _savable_values(
            self, Model, values, baseline, names, creating=False):
        result = {}
        for name in names:
            if name not in Model._fields:
                continue
            field = Model._fields[name]
            if getattr(field, 'readonly', False):
                continue
            value = values.get(name)
            if field._type in {'many2many', 'one2many'}:
                current = list(value or [])
                previous = [] if creating else list(baseline.get(name) or [])
                current_ids = {
                    item.get('id') if isinstance(item, dict) else item
                    for item in current
                    if isinstance(item, int)
                    or (isinstance(item, dict) and item.get('id'))}
                previous_ids = {
                    item.get('id') if isinstance(item, dict) else item
                    for item in previous
                    if isinstance(item, int)
                    or (isinstance(item, dict) and item.get('id'))}
                operations = []
                removed = sorted(previous_ids - current_ids)
                added = sorted(current_ids - previous_ids)
                if removed:
                    operation = (
                        'delete' if field._type == 'one2many'
                        else 'remove')
                    operations.append((operation, removed))
                if added:
                    operations.append(('add', added))
                Target = field.get_target()
                create_values = []
                for item in current:
                    if not isinstance(item, dict) or item.get('id'):
                        continue
                    create_values.append(self._savable_values(
                            Target, item, {}, item.keys(), creating=True))
                if create_values:
                    operations.append(('create', create_values))
                for item in current:
                    if (isinstance(item, dict) and item.get('id')
                            and item.get('values')):
                        item_values = item['values']
                        operations.append((
                                'write', [item['id']], self._savable_values(
                                    Target, item_values, {},
                                    item_values.keys())))
                value = operations
            result[name] = value
        return result

    def _relation_draft_values(self, Model, values, names):
        """Return plain values suitable for an unsaved x2many row."""
        result = {}
        for name in names:
            if name not in Model._fields:
                continue
            field = Model._fields[name]
            if getattr(field, 'readonly', False):
                continue
            result[name] = values.get(name)
        return result

    def save_record(self, tab_id, record_key):
        tab = self._tab(tab_id, kind='window')
        stored = tab['records'][record_key]
        Model = self.pool.get(tab['model'])
        values = decode_value(stored['values'])
        baseline = decode_value(stored.get('baseline', {}))
        context = self.context(decode_value(tab.get('context', {})))
        with Transaction().set_context(context):
            if stored.get('new'):
                names = set(stored.get('dirty', []))
                create_values = self._savable_values(
                    Model, values, baseline, names, creating=True)
                record, = Model.create([create_values])
                record_id = record.id
            else:
                record_id = stored['id']
                write_values = self._savable_values(
                    Model, values, baseline, stored.get('dirty', []))
                if write_values:
                    Model.write([Model(record_id)], write_values)
        relation_origin = tab.get('relation_origin')
        if stored.get('new') and relation_origin:
            parent = self.interface.get_tab(relation_origin.get('tab'))
            field_name = relation_origin.get('field')
            Parent = self.pool.get(parent['model']) if parent else None
            if (parent and Parent and field_name in Parent._fields
                    and parent.get('kind') == 'wizard'):
                relation_field = Parent._fields[field_name]
                if relation_field._type in {'many2one', 'one2one'}:
                    relation_value = record_id
                else:
                    relation_value = list(
                        decode_value(parent.get('values', {})).get(
                            field_name) or [])
                    if record_id not in relation_value:
                        relation_value.append(record_id)
                self.update_wizard_field(
                    parent['id'], field_name, relation_value)
                parent_values = decode_value(parent.get('values', {}))
                parent_values[field_name] = relation_value
                parent['values'] = encode_value(parent_values)
            elif parent and Parent and parent.get('kind') == 'window':
                parent_record = parent.get('records', {}).get(
                    relation_origin.get('record'))
                if parent_record and field_name in Parent._fields:
                    relation_field = Parent._fields[field_name]
                    if relation_field._type in {'many2one', 'one2one'}:
                        relation_value = record_id
                    else:
                        relation_value = list(decode_value(
                                parent_record.get('values', {})).get(
                                    field_name) or [])
                        if record_id not in relation_value:
                            relation_value.append(record_id)
                    self.update_field(
                        parent['id'], parent_record['key'],
                        field_name, relation_value)
                    parent_values = decode_value(
                        parent_record.get('values', {}))
                    parent_values[field_name] = relation_value
                    parent_record['values'] = encode_value(parent_values)
        old_key = record_key
        if stored.get('new'):
            tab['records'].pop(old_key)
            new_key = str(record_id)
            tab['record_order'] = [
                new_key if key == old_key else key
                for key in tab['record_order']
                ]
            tab['current_record'] = new_key
            tab['selected'] = [
                new_key if key == old_key else key
                for key in tab.get('selected', [])
                ]
        else:
            stored['dirty'] = []
        loaded_ids = [
            record['id']
            for record in tab['records'].values()
            if record.get('id')
            ]
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(
            view.get('arch') or '<form/>')
        on_write = root.attrib.get('on_write')
        if on_write:
            callback = getattr(Model, on_write, None)
            if callback:
                with Transaction().set_context(context):
                    loaded_ids.extend(callback([record_id]) or [])
                loaded_ids = list(dict.fromkeys(loaded_ids))
        if record_id not in loaded_ids:
            loaded_ids.append(record_id)
        self.load_tab(tab, ids=loaded_ids)
        tab['current_record'] = str(record_id)
        tab['selected'] = [str(record_id)]
        self.save()
        return tab['records'][str(record_id)]

    def save_records(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        keys = [
            key for key, record in tab['records'].items()
            if record.get('dirty')
            ]
        for key in list(keys):
            if key in tab['records']:
                self.save_record(tab_id, key)
        return self._tab(tab_id)

    def save_relation_draft(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        if not tab.get('relation_draft'):
            raise ValueError(_('This tab is not a relation draft'))
        origin = tab.get('relation_origin') or {}
        parent = self._tab(origin.get('tab'))
        record_key = tab.get('current_record')
        stored = tab.get('records', {}).get(record_key)
        if not stored or not stored.get('new'):
            raise ValueError(_('Unknown relation draft'))

        Model = self.pool.get(tab['model'])
        values = decode_value(stored.get('values', {}))
        names = set(stored.get('dirty', []))
        create_values = self._relation_draft_values(Model, values, names)
        create_values.pop(tab.get('relation_parent_field'), None)

        field_name = origin.get('field')
        if parent.get('kind') == 'wizard':
            parent_values = decode_value(parent.get('values', {}))
            relation_values = list(parent_values.get(field_name) or [])
            if origin.get('item'):
                for index, item in enumerate(relation_values):
                    if WidgetRenderer.x2many_item_key(
                            item, index) == origin['item']:
                        relation_values[index] = create_values
                        break
                else:
                    raise ValueError(_('Unknown related record'))
            else:
                relation_values.append(create_values)
            self.update_wizard_field(
                parent['id'], field_name, relation_values)
        elif parent.get('kind') == 'window':
            parent_record = parent.get('records', {}).get(
                origin.get('record'))
            if not parent_record:
                raise ValueError(_('Unknown relation parent'))
            parent_values = decode_value(parent_record.get('values', {}))
            relation_values = list(parent_values.get(field_name) or [])
            if origin.get('item'):
                for index, item in enumerate(relation_values):
                    if WidgetRenderer.x2many_item_key(
                            item, index) == origin['item']:
                        relation_values[index] = create_values
                        break
                else:
                    raise ValueError(_('Unknown related record'))
            else:
                relation_values.append(create_values)
            self.update_field(
                parent['id'], parent_record['key'],
                field_name, relation_values)
        else:
            raise ValueError(_('Unknown relation parent'))

        self.interface.close(tab_id)
        self.interface.activate(parent['id'])
        self.save()
        return parent

    def delete_record(self, tab_id, record_key):
        tab = self._tab(tab_id, kind='window')
        stored = tab['records'][record_key]
        if not stored.get('new'):
            Model = self.pool.get(tab['model'])
            Model.delete([Model(stored['id'])])
        tab['records'].pop(record_key, None)
        tab['record_order'] = [
            key for key in tab['record_order'] if key != record_key]
        tab['selected'] = [
            key for key in tab.get('selected', []) if key != record_key]
        tab['current_record'] = (
            tab['record_order'][0] if tab['record_order'] else None)
        tab['dirty'] = any(
            record.get('dirty') for record in tab['records'].values())
        context = self.context(decode_value(tab.get('context', {})))
        with Transaction().set_context(context):
            self._update_window_counts(
                tab, self.pool.get(tab['model']),
                decode_value(tab.get('view', {})))
        self.save()
        return tab

    def delete_records(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        keys = tab.get('selected') or [tab.get('current_record')]
        keys = [key for key in keys if key in tab['records']]
        Model = self.pool.get(tab['model'])
        records = [
            Model(tab['records'][key]['id'])
            for key in keys if tab['records'][key].get('id')
            ]
        if records:
            Model.delete(records)
        for key in keys:
            tab['records'].pop(key, None)
        tab['record_order'] = [
            key for key in tab['record_order'] if key not in keys]
        tab['selected'] = []
        tab['current_record'] = (
            tab['record_order'][0] if tab['record_order'] else None)
        tab['dirty'] = any(
            record.get('dirty') for record in tab['records'].values())
        context = self.context(decode_value(tab.get('context', {})))
        with Transaction().set_context(context):
            self._update_window_counts(
                tab, Model, decode_value(tab.get('view', {})))
        self.save()
        return tab

    def revert_record(self, tab_id, record_key):
        tab = self._tab(tab_id, kind='window')
        stored = tab['records'][record_key]
        if stored.get('new'):
            return self.delete_record(tab_id, record_key)
        stored['values'] = stored.get('baseline', {})
        stored['dirty'] = []
        tab['dirty'] = any(
            record.get('dirty') for record in tab['records'].values())
        self.save()
        return tab

    def revert_records(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        dirty_keys = [
            key for key, record in tab['records'].items()
            if record.get('dirty')]
        for key in dirty_keys:
            if key in tab['records']:
                self.revert_record(tab_id, key)
        return self._tab(tab_id)

    def duplicate(self, tab_id):
        tab = self._tab(tab_id, kind='window')
        keys = tab.get('selected') or [tab.get('current_record')]
        records = [
            tab['records'][key] for key in keys
            if key and key in tab['records']
            and not tab['records'][key].get('new')
            ]
        if not records:
            return tab
        Model = self.pool.get(tab['model'])
        copies = Model.copy([Model(record['id']) for record in records])
        loaded_ids = [
            record['id']
            for record in tab['records'].values()
            if record.get('id')
            ]
        loaded_ids.extend(record.id for record in copies)
        self.load_tab(tab, ids=loaded_ids)
        tab['selected'] = [str(record.id) for record in copies]
        tab['current_record'] = tab['selected'][0]
        self.save()
        return tab

    def run_button(
            self, tab_id, button_name, button_type='class',
            record_key=None):
        tab = self._tab(tab_id, kind='window')
        if record_key:
            if record_key not in tab['records']:
                raise ValueError(_('Unknown record %s') % record_key)
            tab['current_record'] = record_key
            if record_key not in tab.get('selected', []):
                tab['selected'] = [record_key]
        keys = tab.get('selected') or [tab.get('current_record')]
        Model = self.pool.get(tab['model'])
        if button_name not in Model._buttons:
            raise ValueError(_('Unknown button %s') % button_name)
        if button_type == 'instance':
            key = tab.get('current_record')
            if not key or key not in tab['records']:
                raise ValueError(_('Select a record first'))
            stored = tab['records'][key]
            values = decode_value(stored['values'])
            record = Model(
                stored.get('id'), **self._record_values(Model, values))
            before = encode_value(record._default_values)
            getattr(record, button_name)()
            changes = self._record_changes(record, before)
            values.update(changes)
            stored['values'] = encode_value(values)
            stored['dirty'] = sorted(
                set(stored.get('dirty', [])) | set(changes))
            tab['dirty'] = any(
                record.get('dirty') for record in tab['records'].values())
            self.save()
            return tab
        record_ids = []
        for key in list(keys):
            if key in tab['records'] and tab['records'][key].get('dirty'):
                stored = self.save_record(tab_id, key)
                record_ids.append(stored['id'])
            elif key in tab['records'] and tab['records'][key].get('id'):
                record_ids.append(tab['records'][key]['id'])
        tab = self._tab(tab_id, kind='window')
        records = [Model(record_id) for record_id in record_ids]
        if not records:
            raise ValueError(_('Select a saved record first'))
        result = getattr(Model, button_name)(records)
        if result:
            if isinstance(result, str):
                self.client_action(tab, result)
            elif isinstance(result, dict):
                self.open_action(result, {
                        'model': tab['model'],
                        'ids': [record.id for record in records],
                        'id': records[0].id,
                        })
            elif isinstance(result, int):
                self.open_action(result, {
                        'model': tab['model'],
                        'ids': [record.id for record in records],
                        'id': records[0].id,
                        })
        if tab.get('view_type') == 'tree':
            self.load_tab(tab)
        else:
            self.load_tab(tab, ids=record_ids)
        selected = [
            str(record_id) for record_id in record_ids
            if str(record_id) in tab.get('records', {})]
        tab['selected'] = selected
        tab['current_record'] = selected[0] if selected else None
        self.save()
        return tab

    def client_action(self, tab, action):
        if action == 'new':
            self.new_record(tab['id'])
        elif action in {'delete', 'remove'}:
            self.delete_records(tab['id'])
        elif action == 'copy':
            self.duplicate(tab['id'])
        elif action in {'next', 'previous'}:
            order = tab.get('record_order', [])
            current = tab.get('current_record')
            if current in order:
                index = order.index(current)
                index += 1 if action == 'next' else -1
                if 0 <= index < len(order):
                    tab['current_record'] = order[index]
                    tab['selected'] = [order[index]]
        elif action == 'close':
            self.close_tab(tab['id'])
        elif action.startswith('switch '):
            view_type = action.split(' ', 2)[1]
            self.switch_view(tab['id'], view_type)
        elif action == 'reload':
            self.load_tab(tab)
        elif action in {'reload menu', 'reload context'}:
            # The next rendered shell/menu reads fresh preferences and menus.
            pass

    def toolbar_action(self, tab_id, action_id):
        tab = self._tab(tab_id, kind='window')
        toolbar = decode_value(tab.get('toolbar', {}))
        action = None
        action_category = None
        for category in ('print', 'action', 'relate'):
            for candidate in toolbar.get(category, []):
                if int(candidate['id']) == int(action_id):
                    action = dict(candidate)
                    action_category = category
                    break
        if not action:
            raise KeyError(_('Toolbar action %s not found') % action_id)
        keys = tab.get('selected') or [tab.get('current_record')]
        ids = []
        for key in list(keys):
            if key in tab['records'] and tab['records'][key].get('dirty'):
                stored = self.save_record(tab_id, key)
                ids.append(stored['id'])
            elif key in tab['records'] and tab['records'][key].get('id'):
                ids.append(tab['records'][key]['id'])
        data = {
                'model': tab['model'],
                'ids': ids,
                'id': ids[0] if ids else None,
                }
        if action_category == 'relate':
            names = []
            Model = self.pool.get(tab['model'])
            for id_ in ids[:5]:
                names.append(str(Model(id_).rec_name))
            if len(ids) > 5:
                names.append('...')
            if names:
                action['name'] = '%s (%s)' % (
                    action.get('name') or '', ', '.join(names))
        if action.get('type') == 'ir.action.report':
            key = self.queue_report(action, data)
            self.save()
            return {'report_key': key}
        return self.open_action(action, data)

    def execute_report(self, action, data, extra_context=None):
        Report = self.pool.get(action['report_name'], type='report')
        context = self.context(extra_context, data)
        context['direct_print'] = action.get('direct_print', False)
        report_data = dict(data)
        report_data['action_id'] = action.get('id')
        with Transaction().set_context(context):
            extension, content, direct_print, filename = Report.execute(
                data.get('ids', []), report_data)
        mimetype = {
            'pdf': 'application/pdf',
            'csv': 'text/csv',
            'html': 'text/html',
            'txt': 'text/plain',
            'zip': 'application/zip',
            }.get(extension, 'application/octet-stream')
        response = Response(content, content_type=mimetype)
        response.headers['Content-Disposition'] = (
            '%s; filename="%s.%s"' % (
                'inline' if direct_print else 'attachment',
                filename, extension))
        response.headers['X-Cassini-Direct-Print'] = (
            'true' if direct_print else 'false')
        response.headers['X-Cassini-Report-Type'] = extension
        response.headers['X-Cassini-Printer'] = (
            base64.urlsafe_b64encode(
                str(filename or '').encode('utf-8')).decode('ascii'))
        return response

    @staticmethod
    def _csv_parameters(delimiter, quotechar):
        delimiter = delimiter or ','
        quotechar = quotechar or '"'
        if len(delimiter) != 1:
            raise ValueError(_(
                    'The CSV delimiter must be one character'))
        if len(quotechar) != 1:
            raise ValueError(_(
                    'The CSV quote character must be one character'))
        return delimiter, quotechar

    @staticmethod
    def _csv_value(value, locale_format, language):
        if value is None:
            return ''
        if isinstance(value, bytes):
            return base64.b64encode(value).decode('ascii')
        if not locale_format:
            if isinstance(value, datetime):
                return value.isoformat(sep=' ')
            if isinstance(value, (date, time)):
                return value.isoformat()
            if isinstance(value, timedelta):
                return value.total_seconds()
            if isinstance(value, bool):
                return int(value)
            return value
        if isinstance(value, datetime):
            zone = timezone.get_tzinfo(
                Transaction().context.get('timezone', 'UTC'))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.UTC)
            return language.strftime(value.astimezone(zone).replace(
                    tzinfo=None))
        if isinstance(value, (date, time)):
            return language.strftime(value)
        if isinstance(value, timedelta):
            return str(value)
        if isinstance(value, bool):
            return language.format('%d', int(value), grouping=True)
        if isinstance(value, (Decimal, float, int)):
            if isinstance(value, float):
                if not math.isfinite(value):
                    return str(value)
                raw = format(Decimal(str(value)), 'f')
            else:
                raw = format(value, 'f')
            if '.' in raw:
                integer, fraction = raw.split('.', 1)
                fraction = fraction.rstrip('0')
            else:
                integer, fraction = raw, ''
            formatted = language.format(
                '%d', int(integer or '0'), grouping=True)
            if fraction:
                formatted += language.decimal_point + fraction
            return formatted
        return value

    def export(
            self, tab_id, export_id=None, fields_names=None, header=True,
            records='listed', ignore_search_limit=False,
            delimiter=',', quotechar='"', locale_format=True):
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        delimiter, quotechar = self._csv_parameters(
            delimiter, quotechar)
        export_definition = None
        if export_id:
            toolbar = decode_value(tab.get('toolbar', {}))
            export_definition = next((
                    definition
                    for definition in toolbar.get('exports', [])
                    if int(definition['id']) == int(export_id)
                    ), None)
            if not export_definition:
                raise ValueError(_('Unknown predefined export'))
        if export_definition:
            fields_names = [
                field['name']
                for field in export_definition.get('export_fields.', [])]
            header = bool(export_definition.get('header'))
            records = export_definition.get('records') or 'selected'
            ignore_search_limit = bool(
                export_definition.get('ignore_search_limit'))
            filename = export_definition['name']
        else:
            fields_names = list(fields_names or [])
            filename = tab['model'].replace('.', '_')
        if not fields_names:
            raise ValueError(_('Select at least one field'))
        if records not in {'selected', 'listed'}:
            raise ValueError(_('Unknown CSV record selection'))
        view = decode_value(tab['view'])
        context = self.context(decode_value(tab.get('context', {})))
        if not tab.get('active_only', True):
            context['active_test'] = False
        with Transaction().set_context(context):
            if records == 'selected':
                keys = tab.get('selected') or (
                    [tab.get('current_record')]
                    if tab.get('current_record') else [])
                ids = [
                    tab['records'][key]['id'] for key in keys
                    if key in tab['records']
                    and tab['records'][key].get('id')]
                rows = Model.export_data(
                    [Model(id_) for id_ in ids],
                    fields_names, header=header)
            elif view.get('field_childs'):
                ids = [
                    tab['records'][key]['id']
                    for key in tab.get('record_order', [])
                    if key in tab['records']
                    and tab['records'][key].get('id')]
                rows = Model.export_data(
                    [Model(id_) for id_ in ids],
                    fields_names, header=header)
            else:
                domain = self._update_window_counts(tab, Model, view)
                rows = Model.export_data_domain(
                    domain, fields_names,
                    offset=(
                        0 if ignore_search_limit
                        else tab.get('offset', 0)),
                    limit=(
                        None if ignore_search_limit
                        else tab.get('limit', 1000)),
                    order=decode_value(tab.get('order')),
                    header=header)
            Lang = self.pool.get('ir.lang')
            language = Lang.get(Transaction().language)
            rows = [[
                    self._csv_value(value, locale_format, language)
                    for value in row]
                for row in rows]
        output = io.StringIO()
        writer = csv.writer(
            output, delimiter=delimiter, quotechar=quotechar)
        writer.writerows(rows)
        response = Response(
            output.getvalue(), content_type='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s.csv"' % secure_filename(filename))
        return response

    def import_csv(
            self, tab_id, content, fields_names=None, encoding='utf-8',
            skip=0, delimiter=',', quotechar='"'):
        tab = self._tab(tab_id, kind='window')
        Model = self.pool.get(tab['model'])
        delimiter, quotechar = self._csv_parameters(
            delimiter, quotechar)
        try:
            codecs.lookup(encoding)
            text = content.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exception:
            raise ValueError(
                _('The CSV file could not be decoded with %(encoding)s') % {
                    'encoding': encoding,
                    }) from exception
        if text.startswith('\ufeff'):
            text = text[1:]
        rows = list(csv.reader(
                io.StringIO(text), delimiter=delimiter,
                quotechar=quotechar))
        if not rows:
            raise ValueError(_('The CSV file is empty'))
        skip = max(0, int(skip or 0))
        if fields_names:
            rows = rows[skip:]
        else:
            fields_names = rows.pop(0)
        if not fields_names or any(not name for name in fields_names):
            raise ValueError(
                _('Select at least one field to import'))
        count = Model.import_data(fields_names, rows)
        self.load_tab(tab)
        self.save()
        return tab, count

    @staticmethod
    def binary_download_response(content, filename):
        """Build a download response for a binary field value."""
        if not isinstance(content, bytes):
            content = bytes(content) if isinstance(
                content, (bytearray, memoryview)) else b''
        filename = secure_filename(str(filename)) or 'binary'
        mimetype = mimetypes.guess_type(filename)[0]
        response = Response(
            content, content_type=mimetype or 'application/octet-stream')
        response.headers['Content-Disposition'] = (
            'attachment; filename="%s"' % filename)
        return response

    def binary_response(self, tab_id, record_key, field_name):
        tab = self._tab(tab_id, kind='window')
        record = tab['records'][record_key]
        values = decode_value(record['values'])
        content = values.get(field_name) or b''
        Model = self.pool.get(tab['model'])
        if not isinstance(content, bytes) and record.get('id'):
            content = getattr(Model(record['id']), field_name) or b''
        view = decode_value(tab.get('view', {}))
        definition = view.get('fields', {}).get(field_name, {})
        filename_field = (
            definition.get('filename')
            or getattr(Model._fields.get(field_name), 'filename', None))
        if not filename_field:
            root = ElementTree.fromstring(view.get('arch') or '<form/>')
            for node in root.iter('field'):
                if node.attrib.get('name') == field_name:
                    filename_field = node.attrib.get('filename')
                    if filename_field:
                        break
        return self.binary_download_response(
            content, values.get(filename_field) or field_name)

    def state_token(self):
        raw = json.dumps(
            encode_value(self.interface.data),
            sort_keys=True, separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(raw[:48]).decode()

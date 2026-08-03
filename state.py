import base64
import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from dominate.tags import div
from trytond.cache import Cache
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.modules.xgettext import _
from trytond.modules.voyager.voyager import Component
from trytond.transaction import Transaction
from werkzeug.wrappers import Response

from .i18n import message_id

STATE_VERSION = 1
WORKSPACE_SESSION_UNIQUE = (
    'A Cassini session can only have one workspace.')
_WORKSPACE_CACHE = Cache(
    'cassini.workspace.session', duration=10 * 60, context=False)
_HTMX_ATTRIBUTE = re.compile(r'\bhx_([a-z_]+)(?==)')


def normalize_htmx_markup(markup):
    """Translate Python-safe HTMX attribute names to their HTML spelling."""
    return _HTMX_ATTRIBUTE.sub(
        lambda match: 'hx-' + match.group(1).replace('_', '-'),
        markup)


def encode_value(value):
    """Return a JSON-safe representation which preserves Tryton value types."""
    if isinstance(value, datetime):
        return {'__type__': 'datetime', 'value': value.isoformat()}
    if isinstance(value, date):
        return {'__type__': 'date', 'value': value.isoformat()}
    if isinstance(value, time):
        return {'__type__': 'time', 'value': value.isoformat()}
    if isinstance(value, timedelta):
        return {'__type__': 'timedelta', 'value': value.total_seconds()}
    if isinstance(value, Decimal):
        return {'__type__': 'decimal', 'value': str(value)}
    if isinstance(value, bytes):
        return {
            '__type__': 'bytes',
            'value': base64.b64encode(value).decode('ascii'),
            }
    if isinstance(value, tuple):
        return {
            '__type__': 'tuple',
            'value': [encode_value(item) for item in value],
            }
    if isinstance(value, set):
        return {
            '__type__': 'set',
            'value': [encode_value(item) for item in value],
            }
    if isinstance(value, list):
        return [encode_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): encode_value(item)
            for key, item in value.items()
            }
    if hasattr(value, 'id') and hasattr(value, '__name__'):
        return {
            '__type__': 'record',
            'model': value.__name__,
            'id': value.id,
            }
    return value


def decode_value(value):
    """Restore a value produced by :func:`encode_value`."""
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    # fields.Dict freezes sequences as tuples when values leave its cache.
    # InterfaceState is intentionally mutable, so normalise those tuples at
    # the storage boundary. Explicit tuple values use the tagged form below.
    if isinstance(value, tuple):
        return [decode_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    type_ = value.get('__type__')
    if type_ == 'datetime':
        return datetime.fromisoformat(value['value'])
    if type_ == 'date':
        return date.fromisoformat(value['value'])
    if type_ == 'time':
        return time.fromisoformat(value['value'])
    if type_ == 'timedelta':
        return timedelta(seconds=value['value'])
    if type_ == 'decimal':
        return Decimal(value['value'])
    if type_ == 'bytes':
        return base64.b64decode(value['value'])
    if type_ == 'tuple':
        return tuple(decode_value(item) for item in value['value'])
    if type_ == 'set':
        return {decode_value(item) for item in value['value']}
    if type_ == 'record':
        from trytond.pool import Pool
        return Pool().get(value['model'])(value['id'])
    return {
        key: decode_value(item)
        for key, item in value.items()
        }


def empty_state():
    return {
        'version': STATE_VERSION,
        'active_tab': None,
        'tabs': [],
        'components': {},
        'preferences_open': False,
        'notice': None,
        }


class InterfaceState:
    """Mutable, UI-agnostic workspace document.

    The class deliberately knows nothing about Tryton XML views. Custom web
    applications may use ``components`` only and still obtain the same
    persistence and fragment update semantics as the Sao-compatible client.
    """

    def __init__(self, data=None):
        self.data = copy.deepcopy(data or empty_state())
        self.data.setdefault('version', STATE_VERSION)
        self.data.setdefault('tabs', [])
        self.data.setdefault('components', {})
        self.data.setdefault('active_tab', None)

    @property
    def tabs(self):
        return self.data['tabs']

    @property
    def active_tab(self):
        tab_id = self.data.get('active_tab')
        return self.get_tab(tab_id) if tab_id else None

    def get_tab(self, tab_id):
        for tab in self.tabs:
            if tab['id'] == tab_id:
                return tab
        return None

    def add_tab(self, values):
        tab = {
            'id': uuid.uuid4().hex,
            'title': values.get('title') or values.get('model') or 'Tryton',
            'kind': values.get('kind', 'window'),
            'dirty': False,
            }
        tab.update(values)
        self.tabs.append(tab)
        self.data['active_tab'] = tab['id']
        return tab

    def activate(self, tab_id):
        if not self.get_tab(tab_id):
            raise KeyError(_('Unknown tab %s') % tab_id)
        self.data['active_tab'] = tab_id

    def close(self, tab_id):
        index = next((
                index for index, tab in enumerate(self.tabs)
                if tab['id'] == tab_id), None)
        if index is None:
            return
        self.tabs.pop(index)
        if self.data.get('active_tab') == tab_id:
            if self.tabs:
                self.data['active_tab'] = self.tabs[
                    min(index, len(self.tabs) - 1)]['id']
            else:
                self.data['active_tab'] = None

    def component(self, key, default=None):
        components = self.data['components']
        if key not in components:
            components[key] = copy.deepcopy(default or {})
        return components[key]


class Workspace(ModelSQL, ModelView):
    'Cassini Workspace'
    __name__ = 'cassini.workspace'
    _order = [('id', 'ASC')]

    session = fields.Many2One(
        'www.session', 'Session', required=True, ondelete='CASCADE')
    user = fields.Many2One(
        'res.user', 'User', required=True, ondelete='CASCADE')
    state = fields.Dict(None, 'State', required=True)
    revision = fields.Integer('Revision', required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints += [
            ('session_unique', Unique(table, table.session),
                'cassini.' + message_id(WORKSPACE_SESSION_UNIQUE)),
            ]

    @staticmethod
    def default_state():
        return empty_state()

    @staticmethod
    def default_revision():
        return 0

    @classmethod
    def get(cls, session, user):
        cached = _WORKSPACE_CACHE.get(session.id)
        if cached and cached[1] == user.id:
            return cls(cached[0])
        workspaces = cls.search([
                ('session', '=', session.id),
                ], limit=1)
        if workspaces:
            workspace, = workspaces
            if workspace.user != user:
                workspace.user = user
                workspace.state = empty_state()
                workspace.revision = workspace.revision + 1
                workspace.save()
            _WORKSPACE_CACHE.set(
                session.id, (workspace.id, user.id))
            return workspace
        workspace = cls(
            session=session,
            user=user,
            state=empty_state(),
            revision=0)
        workspace.save()
        _WORKSPACE_CACHE.set(
            session.id, (workspace.id, user.id))
        return workspace

    @classmethod
    def delete(cls, workspaces):
        super().delete(workspaces)
        _WORKSPACE_CACHE.clear()

    def interface(self):
        return InterfaceState(decode_value(self.state))

    def store(self, interface):
        self.state = encode_value(interface.data)
        self.revision += 1
        self.save()

    def reset(self):
        self.state = empty_state()
        self.revision += 1
        self.save()


class StatefulComponent(Component):
    """Base Voyager component backed by the current persistent workspace."""
    'Stateful Component'
    __name__ = 'cassini.stateful.component'
    _cached = False

    component_id = fields.Char('Component ID')

    @property
    def workspace(self):
        if not self.session or not self.session.system_user:
            return None
        return Workspace.get(self.session, self.session.system_user)

    def get_component_state(self, default=None):
        workspace = self.workspace
        if not workspace:
            return copy.deepcopy(default or {})
        return workspace.interface().component(
            self.component_id or self.__name__, default)

    def update_component_state(self, values):
        workspace = self.workspace
        if not workspace:
            return
        interface = workspace.interface()
        interface.component(self.component_id or self.__name__).update(values)
        workspace.store(interface)

    def render(self):
        return div()


_STATE_COMPONENTS = {}


def register_state_component(name, renderer):
    """Register a reusable renderer for a custom, non-XML UI component."""
    if not name or not callable(renderer):
        raise ValueError(_('A component name and callable renderer are required'))
    _STATE_COMPONENTS[name] = renderer


def render_state_component(name, component_state, context=None):
    try:
        renderer = _STATE_COMPONENTS[name]
    except KeyError:
        raise ValueError(_('Unknown state component %s') % name)
    return renderer(component_state, context or {})


@dataclass
class Fragment:
    target: str
    content: object
    swap: str = 'outerHTML'

    def render(self, out_of_band=False):
        content = self.content
        if hasattr(content, 'render'):
            if out_of_band:
                content['hx-swap-oob'] = '%s:#%s' % (
                    self.swap, self.target)
            return normalize_htmx_markup(content.render())
        return str(content)


class FragmentResponse:
    """Build one HTMX response from one or more independently rendered parts."""

    @classmethod
    def response(
            cls, fragments, stream=False, status=200, headers=None,
            all_out_of_band=False):
        fragments = list(fragments)
        if not fragments:
            return Response('', status=status, headers=headers)

        def generate():
            for index, fragment in enumerate(fragments):
                yield fragment.render(
                    out_of_band=all_out_of_band or index > 0)

        if stream:
            headers = dict(headers or {})
            headers.setdefault('X-Accel-Buffering', 'no')
            return Response(
                generate(), status=status, headers=headers,
                content_type='text/html')
        return Response(
            ''.join(generate()), status=status, headers=headers,
            content_type='text/html')


def state_as_json(state):
    return json.dumps(
        encode_value(state), ensure_ascii=False, separators=(',', ':'))


def current_request():
    context = Transaction().context.get('voyager_context')
    # VoyagerContext inherits dict but stores request metadata on attributes;
    # the dictionary itself is empty and therefore false-y.
    return context.request if context is not None else None

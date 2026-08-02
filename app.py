import base64
import json
import mimetypes
import re
import uuid
from datetime import date, datetime, time
from functools import wraps
from urllib.parse import quote
from xml.etree import ElementTree

import dominate
from dominate.tags import (
    a, article, aside, button, details, div, form, h1, h2, h4,
    header, iframe, img, input_, label, li, link, main, meta, nav, option, p,
    script, section, select, span, strong, summary, textarea, ul)
from dominate.util import raw
from trytond.exceptions import (
    LoginException, RateLimitException, TrytonException, UserWarning)
from trytond.model import fields
from trytond.modules.voyager.voyager import Component, Endpoint
from trytond.pool import Pool
from trytond.protocols.wrappers import (
    TRYTON_SESSION_COOKIE, add_auth_cookies, remove_auth_cookies)
from trytond.transaction import Transaction
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from .engine import SaoEngine
from .icons import fullscreen_icon, icon, theme_icon
from .i18n import javascript_translations, translate
from .state import (
    Fragment, FragmentResponse, current_request, decode_value, encode_value,
    normalize_htmx_markup, render_state_component)
from .views import ViewRenderer, WorkspaceRenderer, parse_architecture
from .website import cassini_session_id
from .widgets import HierarchyWidget, WidgetRenderer, dom_id

APP_TYPE = 'cassini'
STATIC = '/cassini-static'
HELP_ICONS = '/cassini-help-icons/'


def optional_model(name):
    try:
        return Pool().get(name)
    except KeyError:
        return None


def is_htmx_request():
    request = current_request()
    return bool(request and request.headers.get('HX-Request'))


def field_attributes(view, name):
    root = parse_architecture(view)

    def find(node, columns):
        try:
            columns = max(1, int(node.attrib.get('col', columns)))
        except (TypeError, ValueError):
            pass
        for child in node:
            if child.tag == 'field' and child.attrib.get('name') == name:
                attributes = dict(child.attrib)
                attributes['_columns'] = columns
                return attributes
            attributes = find(child, columns)
            if attributes is not None:
                return attributes
        return None

    attributes = find(root, root.attrib.get('col', 4))
    if attributes is not None:
        return attributes
    return {}


def relation_source(engine, tab_id, record_key, field_name):
    if tab_id == 'preferences':
        if not engine.interface.data.get('preferences_open'):
            raise ValueError(translate('Preferences are not open'))
        if record_key != str(Transaction().user):
            raise ValueError(translate('Unknown preference record'))
        User = Pool().get('res.user')
        view = User.get_preferences_fields_view()
        state = engine.interface.component('preferences')
        tab = {
            'id': 'preferences',
            'kind': 'preferences',
            'model': 'res.user',
            'pages': state.setdefault('pages', {}),
            'screen_width': engine.interface.data.get('screen_width'),
            }
        record = {
            'key': record_key,
            'id': Transaction().user,
            'values': decode_value(state.get('values', {})),
            'x2many': state.setdefault('x2many', {}),
            }
        endpoint = 'preferences'
        editable = True
    else:
        tab = engine.interface.get_tab(tab_id)
        if not tab:
            raise ValueError(translate('Unknown record'))
        view = decode_value(tab.get('view', {}))
        if tab.get('kind') == 'wizard':
            if record_key != 'wizard':
                raise ValueError(translate('Unknown record'))
            tab['model'] = view.get('model')
            record = {
                'key': 'wizard',
                'id': None,
                'values': decode_value(tab.get('values', {})),
                'x2many': tab.setdefault('x2many', {}),
                }
            endpoint = 'wizard'
            editable = True
        elif (
                tab.get('kind') == 'window'
                and record_key in tab.get('records', {})):
            record = tab['records'][record_key]
            endpoint = 'record'
            access = tab.get('access', {})
            editable = (
                access.get('create', True)
                if record.get('new') else access.get('write', True))
        else:
            raise ValueError(translate('Unknown record'))
    definition = view.get('fields', {}).get(field_name)
    Parent = Pool().get(tab['model'])
    field = Parent._fields.get(field_name)
    if (
            not definition
            or not definition.get('relation')
            or not field
            or field._type not in {
                'many2one', 'one2one', 'one2many', 'many2many'}):
        raise ValueError(translate('Unknown relation field'))
    renderer = WidgetRenderer(
        tab, record, view, editable=editable, endpoint=endpoint)
    return tab, record, view, renderer, Parent, field, endpoint


def update_relation_source(
        engine, tab_id, record_key, field_name, view, endpoint, value):
    if endpoint == 'preferences':
        engine.update_preference(view, field_name, value)
    elif endpoint == 'wizard':
        engine.update_wizard_field(tab_id, field_name, value)
    else:
        engine.update_field(
            tab_id, record_key, field_name, value,
            field_attributes(view, field_name))
    return relation_source(engine, tab_id, record_key, field_name)


def html_response(tag, headers=None):
    markup = normalize_htmx_markup(tag.render())
    return Response(markup, content_type='text/html', headers=headers)


def screen_response(engine, tab, all_out_of_band=False):
    renderer = ViewRenderer(engine.interface)
    return FragmentResponse.response([
            Fragment('screen-' + tab['id'], renderer.screen(tab)),
            Fragment(
                'workspace-tabs',
                WorkspaceRenderer(engine.interface).tabs()),
            ], stream=True, all_out_of_band=all_out_of_band)


def screen_and_close_modal_response(engine, tab):
    renderer = ViewRenderer(engine.interface)
    return FragmentResponse.response([
            Fragment('screen-' + tab['id'], renderer.screen(tab)),
            Fragment(
                'workspace-tabs',
                WorkspaceRenderer(engine.interface).tabs()),
            Fragment(
                'modal',
                div(id='modal', cls='vs-modal-host')),
            ], stream=True)


def workspace_response(
        engine, headers=None, extra_fragments=None, all_out_of_band=False):
    fragments = [
        Fragment(
            'workspace',
            WorkspaceRenderer(engine.interface).render(
                include_tabs=False)),
        Fragment(
            'workspace-tabs',
            WorkspaceRenderer(engine.interface).tabs()),
        ]
    fragments.extend(extra_fragments or [])
    return FragmentResponse.response(
        fragments, stream=True, headers=headers,
        all_out_of_band=all_out_of_band)


def active_workspace_url(engine):
    active = engine.interface.active_tab
    if active:
        return Pool().get('cassini.activate.tab').url(
            tab=active['id'])
    return Pool().get('cassini.shell').url()


def revision_dialog(tab):
    CloseRevisions = Pool().get('cassini.close.revisions')
    SetRevision = Pool().get('cassini.set.revision')
    revisions = decode_value(tab.get('revisions', []))
    with div(
            cls='vs-modal-backdrop',
            data_close_url=CloseRevisions.url(tab=tab['id'])) as backdrop:
        with section(
                role='dialog', aria_modal='true',
                aria_labelledby='revisions-title',
                cls='vs-modal'):
            h2(translate('Revisions'), id='revisions-title')
            with ul(cls='vs-revision-list'):
                with li():
                    button(
                        translate('Current values'), type='button',
                        cls='vs-link-button',
                        hx_post=SetRevision.url(
                            tab=tab['id'], revision='current'),
                        hx_target='#workspace',
                        hx_swap='outerHTML')
                for index, revision in enumerate(revisions):
                    timestamp, _record_id, user = revision
                    with li():
                        button(
                            '%s — %s' % (timestamp, user or ''),
                            type='button', cls='vs-link-button',
                            hx_post=SetRevision.url(
                                tab=tab['id'], revision=str(index)),
                            hx_target='#workspace',
                            hx_swap='outerHTML')
            button(
                translate('Close'), type='button', cls='vs-button',
                hx_post=CloseRevisions.url(tab=tab['id']),
                hx_target='#modal',
                hx_swap='innerHTML')
    return backdrop


def message_response(message, description='', level='error'):
    with div(
            id='notifications', cls='vs-notifications',
            hx_swap_oob='outerHTML:#notifications',
            aria_live='polite') as host:
        with div(
                cls='vs-notice vs-notice-' + level,
                role='alert'):
            p(message)
            if description:
                p(description, cls='vs-muted')
    return html_response(host, {'HX-Reswap': 'none'})


def has_unsaved_changes(tab, form_only=False):
    if not tab or tab.get('kind') != 'window' or not tab.get('dirty'):
        return False
    if form_only and tab.get('view_type') != 'form':
        return False
    return any(
        record.get('dirty')
        for record in tab.get('records', {}).values())


def unsaved_changes_response(engine, tab, action, parameters=None):
    ResolveUnsavedChanges = Pool().get(
        'cassini.resolve.unsaved.changes')
    dirty_records = [
        record for record in tab.get('records', {}).values()
        if record.get('dirty')]
    field_count = sum(
        len(record.get('dirty', []))
        for record in dirty_records)
    record_count = len(dirty_records)
    if field_count == 1:
        if record_count == 1:
            count_label = translate(
                '%(fields)d modified field in %(records)d record',
                fields=field_count, records=record_count)
        else:
            count_label = translate(
                '%(fields)d modified field in %(records)d records',
                fields=field_count, records=record_count)
    elif record_count == 1:
        count_label = translate(
            '%(fields)d modified fields in %(records)d record',
            fields=field_count, records=record_count)
    else:
        count_label = translate(
            '%(fields)d modified fields in %(records)d records',
            fields=field_count, records=record_count)
    current = tab.get('records', {}).get(tab.get('current_record'))
    if not current or not current.get('dirty'):
        current = dirty_records[0]
    values = decode_value(current.get('values', {}))
    Model = Pool().get(tab['model'])
    record_name = (
        values.get(getattr(Model, '_rec_name', None))
        or values.get('rec_name')
        or (translate('New record')
            if current.get('new') else tab['title']))
    action_labels = {
        'close-tab': (
            translate('close this tab'),
            translate('Close without saving'),
            translate('Save and close')),
        'new-record': (
            translate('create another record'),
            translate('Continue without saving'),
            translate('Save and continue')),
        'select-neighbor': (
            translate('open another record'),
            translate('Continue without saving'),
            translate('Save and continue')),
        'switch-view': (
            translate('switch view'),
            translate('Switch without saving'),
            translate('Save and switch')),
        'open-preferences': (
            translate('open preferences'),
            translate('Close without saving'),
            translate('Save and continue')),
        }
    description, discard_label, save_label = action_labels[action]
    values = dict(parameters or {})
    endpoint = ResolveUnsavedChanges.url(
        tab=tab['id'], action=action)
    with div(id='modal', cls='vs-modal-host') as host:
        with div(cls='vs-modal-backdrop'):
            with section(
                    role='alertdialog', aria_modal='true',
                    aria_labelledby='unsaved-title',
                    aria_describedby='unsaved-description',
                    cls='vs-modal vs-unsaved-dialog'):
                with header(cls='vs-unsaved-header'):
                    with div(cls='vs-unsaved-icon'):
                        icon('warning')
                    with div():
                        h2(translate('Unsaved changes'), id='unsaved-title')
                        p(
                            translate(
                                'Choose what to do before you %(action)s.',
                                action=description),
                            id='unsaved-description',
                            cls='vs-muted')
                with div(cls='vs-unsaved-record'):
                    span(translate('Current record'), cls='vs-unsaved-label')
                    strong(str(record_name))
                    span(count_label, cls='vs-unsaved-count')
                with div(cls='vs-unsaved-explanation'):
                    p(
                        translate('Save validates the record and writes the changes '
                        'to Tryton.'))
                    p(
                        translate('Continuing without saving permanently discards '
                        'the current draft.'))
                with div(cls='vs-dialog-actions vs-unsaved-actions'):
                    button(
                        translate('Cancel'), type='button',
                        cls='vs-button',
                        data_close_modal='true',
                        autofocus=True)
                    discard_values = dict(values, decision='discard')
                    with button(
                            type='button',
                            cls='vs-button vs-button-danger',
                            hx_post=endpoint,
                            hx_vals=json.dumps(discard_values),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('undo')
                        span(discard_label)
                    save_values = dict(values, decision='save')
                    with button(
                            type='button',
                            cls='vs-button vs-button-primary',
                            hx_post=endpoint,
                            hx_vals=json.dumps(save_values),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('save')
                        span(save_label)
    if action in {'close-tab', 'open-preferences'}:
        target = 'workspace'
        content = WorkspaceRenderer(engine.interface).render(
            include_tabs=False)
    else:
        target = 'screen-' + tab['id']
        content = ViewRenderer(engine.interface).screen(tab)
    fragments = [
            Fragment(target, content),
            Fragment('modal', host),
            ]
    if target == 'workspace':
        fragments.append(Fragment(
                'workspace-tabs',
                WorkspaceRenderer(engine.interface).tabs()))
    return FragmentResponse.response(fragments)


def warning_response(exception):
    request = current_request()
    target = request.headers.get('HX-Target') if request else None
    with div(
            id='modal', cls='vs-modal-host',
            hx_swap_oob='outerHTML:#modal') as host:
        with div(cls='vs-modal-backdrop'):
            with section(
                    role='alertdialog', aria_modal='true',
                    aria_labelledby='warning-title',
                    cls='vs-modal'):
                h2(exception.message, id='warning-title')
                if exception.description:
                    p(exception.description)
                with form(
                        hx_post=request.path,
                        hx_target=('#' + target) if target else '#workspace',
                        hx_swap='outerHTML'):
                    for name in request.form:
                        if name != '_warning':
                            for value in request.form.getlist(name):
                                input_(
                                    type='hidden', name=name, value=value)
                    input_(
                        type='hidden', name='_warning',
                        value=exception.name)
                    button(
                        translate('Cancel'), type='button', cls='vs-button',
                        data_close_modal='true')
                    button(
                        translate('Continue'), type='submit',
                        cls='vs-button vs-button-primary')
    return html_response(host)


def handle_endpoint_errors(method):
    """Turn expected Tryton errors into HTMX notices and confirmations."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        request = current_request()
        warning = request.form.get('_warning') if request else None
        if warning:
            Warning = Pool().get('res.user.warning')
            Warning.skip(warning, always=False)
        try:
            return method(self, *args, **kwargs)
        except UserWarning as exception:
            return warning_response(exception)
        except TrytonException as exception:
            Transaction().rollback()
            return message_response(
                getattr(exception, 'message', str(exception)),
                getattr(exception, 'description', ''))
        except (KeyError, ValueError) as exception:
            return message_response(str(exception))
    return guarded


class SaoComponent(Component):
    @property
    def engine(self):
        if not self.session.system_user:
            return None
        context = Transaction().context.get('voyager_context')
        if context is not None and hasattr(context, 'sao_engine'):
            return context.sao_engine
        Workspace = Pool().get('cassini.workspace')
        workspace = Workspace.get(
            self.session, self.session.system_user)
        engine = SaoEngine(workspace)
        if context is not None:
            context.sao_engine = engine
        return engine

    def require_user(self):
        if self.session.system_user:
            return None
        LoginPage = Pool().get('cassini.login.page')
        if is_htmx_request():
            return Response('', headers={'HX-Redirect': LoginPage.url()})
        return redirect(LoginPage.url())

    def workspace_fragment(self):
        return WorkspaceRenderer(self.engine.interface).render(
            include_tabs=False)


class SaoEndpoint(SaoComponent, Endpoint):
    _type = APP_TYPE
    _cached = False
    _method = ['GET', 'POST']

    def __init__(self, *args, **kwargs):
        request = current_request()
        if request:
            for name, raw_value in request.args.items():
                if (name not in self._fields
                        or kwargs.get(name) is not None):
                    continue
                field = self._fields[name]
                if field._type == 'boolean':
                    value = str(raw_value).lower() in {
                        '1', 'true', 'on', 'yes'}
                elif field._py_type:
                    try:
                        value = field._py_type(raw_value)
                    except (TypeError, ValueError):
                        value = None
                else:
                    value = raw_value
                kwargs[name] = value
        super().__init__(*args, **kwargs)


class Asset(SaoEndpoint):
    'Cassini Asset'
    __name__ = 'cassini.asset'
    _url = '/asset/<string:name>'

    name = fields.Char('Name')

    def render(self):
        if self.name == 'manifest.json':
            return Response(json.dumps({
                        'name': 'Cassini',
                        'short_name': 'Tryton',
                        'display': 'standalone',
                        'start_url': './',
                        'theme_color': '#1f4b43',
                        'background_color': '#f4f7f5',
                        }), content_type='application/manifest+json')
        return Response('', status=404)


class PageLayout(SaoComponent):
    'Cassini Page Layout'
    __name__ = 'cassini.page.layout'

    def render_page(self, content, page_title='Tryton', theme='light'):
        language = Transaction().language or 'en'
        document = dominate.document(title=page_title, lang=language)
        document['data-theme'] = (
            theme if theme in {'light', 'dark'} else 'light')
        document['class'] = 'dark' if theme == 'dark' else ''
        with document.head:
            meta(charset='utf-8')
            meta(
                name='viewport',
                content='width=device-width, initial-scale=1')
            meta(name='color-scheme', content='light dark')
            meta(
                name='cassini-translations',
                content=json.dumps(
                    javascript_translations(), ensure_ascii=False))
            script(raw(
                """(function () {
                    const url = new URL(window.location.href);
                    if (url.searchParams.has('_cassini_reload')) {
                        url.searchParams.delete('_cassini_reload');
                        window.history.replaceState(
                            window.history.state, '',
                            url.pathname + url.search + url.hash);
                    }
                }());"""))
            link(rel='stylesheet', href=STATIC + '/tailwind-output.css')
            link(rel='stylesheet', href=STATIC + '/app.css')
            link(
                rel='manifest',
                href=Pool().get('cassini.asset').url(
                    name='manifest.json'))
            script(
                src='https://cdn.jsdelivr.net/npm/htmx.org@2.0.7/'
                    'dist/htmx.min.js')
            script(
                src='https://cdnjs.cloudflare.com/ajax/libs/showdown/'
                    '2.1.0/showdown.min.js',
                defer=True)
            script(src=STATIC + '/app.js', defer=True)
        document.body['class'] = 'vs-body'
        # Every Cassini mutation updates the same persistent workspace
        # document.  Keep browser requests in order as well as taking the
        # database row lock so a delayed field change can never overwrite a
        # tab opened immediately afterwards.
        document.body['hx-sync'] = 'this:queue all'
        document.body.add(content)
        return document

    def render(self):
        return self.render_page(div())


class Index(SaoEndpoint):
    'Cassini Index'
    __name__ = 'cassini.index'
    _url = '/'

    def render(self):
        if self.session.system_user:
            Shell = Pool().get('cassini.shell')
            return redirect(Shell.url())
        LoginPage = Pool().get('cassini.login.page')
        return redirect(LoginPage.url())


class LoginForm(SaoComponent):
    'Cassini Login Form'
    __name__ = 'cassini.login.form'
    _cached = False

    error = fields.Char('Error')
    challenge = fields.Char('Challenge')
    challenge_message = fields.Char('Challenge Message')
    challenge_type = fields.Char('Challenge Type')
    username = fields.Char('User')
    password = fields.Char('Password')

    def render(self):
        Login = Pool().get('cassini.login')
        with main(cls='vs-login-page') as page:
            with section(cls='vs-login-card'):
                div('VS', cls='vs-login-mark', aria_hidden='true')
                h1(translate('Sign in'))
                p(
                    translate('Sign in with your Tryton account.'),
                    cls='vs-muted')
                if self.error:
                    p(self.error, role='alert',
                        cls='vs-notice vs-notice-error')
                with form(
                        method='post', action=Login.url(),
                        cls='vs-login-form'):
                    if self.challenge:
                        input_(
                            type='hidden', name='username',
                            value=self.username or '')
                        input_(
                            type='hidden', name='password',
                            value=self.password or '')
                        label(
                            self.challenge_message or self.challenge,
                            html_for='login-challenge', cls='vs-label')
                        input_(
                            id='login-challenge',
                            name=self.challenge,
                            type=(
                                'password'
                                if self.challenge_type == 'password'
                                else 'text'),
                            autocomplete='one-time-code',
                            required=True, autofocus=True,
                            cls='vs-input')
                    else:
                        label(
                            translate('User'), html_for='username',
                            cls='vs-label')
                        input_(
                            id='username', name='username', type='text',
                            value=self.username or '',
                            autocomplete='username', required=True,
                            autofocus=True, cls='vs-input')
                        label(
                            translate('Password'), html_for='password',
                            cls='vs-label')
                        input_(
                            id='password', name='password', type='password',
                            autocomplete='current-password', required=True,
                            cls='vs-input')
                    button(
                        translate('Sign in'), type='submit',
                        cls='vs-button vs-button-primary vs-button-wide')
        return page


class LoginPage(SaoEndpoint):
    'Cassini Login Page'
    __name__ = 'cassini.login.page'
    _url = '/login'

    def render(self):
        if self.session.system_user:
            return redirect(Pool().get('cassini.shell').url())
        pool = Pool()
        PageLayout = pool.get('cassini.page.layout')
        LoginForm = pool.get('cassini.login.form')
        layout = PageLayout(render=False)
        return layout.render_page(LoginForm().tag(), 'Sign in — Tryton')


class Login(SaoEndpoint):
    'Cassini Login'
    __name__ = 'cassini.login'
    _url = '/login-request'

    username = fields.Char('User')
    password = fields.Char('Password')

    def render(self):
        if self.session.system_user:
            return redirect(Pool().get('cassini.shell').url())
        User = Pool().get('res.user')
        Session = Pool().get('ir.session')
        request = current_request()
        parameters = {
            name: value
            for name, value in request.form.items()
            if name != 'username'
            }
        try:
            user_id = User.get_login(
                self.username or '', parameters)
        except LoginException as exception:
            PageLayout = Pool().get('cassini.page.layout')
            LoginForm = Pool().get('cassini.login.form')
            layout = PageLayout(render=False)
            return layout.render_page(
                LoginForm(
                    challenge=exception.name,
                    challenge_message=exception.message,
                    challenge_type=exception.type,
                    username=self.username,
                    password=self.password).tag(),
                'Verify sign in — Tryton')
        except RateLimitException:
            PageLayout = Pool().get('cassini.page.layout')
            LoginForm = Pool().get('cassini.login.form')
            layout = PageLayout(render=False)
            return layout.render_page(
                LoginForm(
                    error='Too many sign-in attempts. Try again later.',
                    username=self.username).tag(),
                'Sign in — Tryton')
        if not user_id:
            PageLayout = Pool().get('cassini.page.layout')
            LoginForm = Pool().get('cassini.login.form')
            layout = PageLayout(render=False)
            return layout.render_page(
                LoginForm(error='The user or password is incorrect.').tag(),
                'Sign in — Tryton')
        with Transaction().set_user(user_id):
            token = Session.new()
        self.session.session_id = cassini_session_id(
            Transaction().database.name, token)
        self.session.save()
        self.session.set_system_user(user_id)
        Workspace = Pool().get('cassini.workspace')
        Workspace.get(self.session, User(user_id))
        response = redirect(Pool().get('cassini.shell').url())
        add_auth_cookies(
            response, Transaction().database.name,
            self.username or '', str(user_id), token)
        return response


class Logout(SaoEndpoint):
    'Cassini Logout'
    __name__ = 'cassini.logout'
    _url = '/logout'

    def render(self):
        request = current_request()
        authentication = request.session if request else None
        if self.session.system_user:
            Workspace = Pool().get('cassini.workspace')
            workspaces = Workspace.search([
                    ('session', '=', self.session.id),
                    ])
            Workspace.delete(workspaces)
        self.session.set_system_user(None)
        if authentication:
            Pool().get('ir.session').remove(authentication.token)
        response = redirect(Pool().get('cassini.login.page').url())
        remove_auth_cookies(response, Transaction().database.name)
        if request and request.cookies.get(TRYTON_SESSION_COOKIE):
            response.delete_cookie('session_id', path='/')
        return response


class Shell(SaoEndpoint):
    'Cassini Shell'
    __name__ = 'cassini.shell'
    _url = '/app'

    def version_changes_dialog(self):
        Notification = optional_model('nantic_connection.notification')
        state = self.engine.interface.component(
            'version_changes', {'dismissed': []})
        dismissed = {
            int(notification_id)
            for notification_id in state.get('dismissed', [])
            }
        updates = (
            Notification.get_notifications([], [], 'version')
            if Notification else [])
        update = next((
                item for item in updates
                if int(item['id']) not in dismissed), None)
        with div(
                id='version-changes-host',
                cls='vs-version-changes-host') as host:
            if not update:
                return host
            content = update.get('notification_html')
            if isinstance(content, (bytes, bytearray)):
                content = bytes(content).decode('utf-8')
            elif isinstance(content, list):
                content = bytes(content).decode('utf-8')
            VersionChanges = Pool().get('cassini.version.changes')
            with div(
                    id='modal-version-changes',
                    cls='vs-modal-backdrop'):
                with section(
                        role='dialog',
                        aria_modal='true',
                        aria_labelledby='version-changes-title',
                        cls='vs-modal vs-version-changes-dialog'):
                    h2(
                        update.get('subject') or translate('Version changes'),
                        id='version-changes-title')
                    div(
                        raw(content or ''),
                        cls='vs-version-changes-content')
                    with div(cls='vs-dialog-actions'):
                        button(
                            translate('Accept'),
                            type='button',
                            cls='vs-button vs-button-primary',
                            hx_post=VersionChanges.url(
                                update=update['id'], action='accept'),
                            hx_target='#version-changes-host',
                            hx_swap='outerHTML')
                        button(
                            translate("Don't show again"),
                            type='button',
                            cls='vs-button',
                            hx_post=VersionChanges.url(
                                update=update['id'], action='never'),
                            hx_target='#version-changes-host',
                            hx_swap='outerHTML')
        return host

    def render_app(self):
        Menu = Pool().get('cassini.menu')
        GlobalSearch = Pool().get('cassini.global.search')
        Preferences = Pool().get('cassini.preferences')
        Logout = Pool().get('cassini.logout')
        ShellControl = Pool().get('cassini.shell.control')
        Demo = Pool().get('cassini.demo')
        HelpPanel = Pool().get('cassini.help.panel')
        assistant_available = bool(optional_model(
                'nantic.chat.conversation'))
        new_shell_state = (
            'shell' not in self.engine.interface.data['components'])
        shell_state = self.engine.interface.component('shell', {
                'panel': 'none',
                'theme': 'light',
                'user_menu': False,
                })
        user_preferences = Pool().get('res.user').get_preferences(False)
        self.engine.start_user_actions(
            user_preferences.get('actions', []))
        user_status = (
            user_preferences.get('status_bar')
            or self.session.system_user.rec_name)
        migrated_shell_state = False
        if shell_state.get('panel') not in {'none', 'menu', 'help'}:
            shell_state['panel'] = (
                'help' if shell_state.get('help_open')
                else 'menu' if shell_state.get('menu_open')
                else 'none')
            migrated_shell_state = True
        if (not assistant_available
                and shell_state.get('panel') == 'help'):
            shell_state['panel'] = 'none'
            migrated_shell_state = True
        panel_state = shell_state['panel']
        if new_shell_state or migrated_shell_state:
            self.engine.save()
        preferences_content = None
        if self.engine.interface.data.get('preferences_open'):
            preferences_content = Preferences().tag()
        elif (self.engine.interface.active_tab
                and self.engine.interface.active_tab.get('revision_open')):
            preferences_content = revision_dialog(
                self.engine.interface.active_tab)

        with div(
                id='cassini',
                cls=(
                    'vs-app min-h-screen bg-slate-50 text-slate-900 '
                    'dark:bg-slate-950 dark:text-slate-100 '
                    'vs-panel-%s') % panel_state,
                data_theme=shell_state.get('theme', 'light'),
                data_panel=panel_state) as app:
            with header(cls='vs-header'):
                with div(cls='vs-header-primary') as header_primary:
                    with nav(
                            cls='vs-shell-controls',
                            aria_label=translate('Side panel')):
                        panel_options = (
                            (
                                ('none', translate('No side panel')),
                                ('menu', translate('Menu')),
                                ('help', translate('Help')))
                            if assistant_available
                            else (('menu', translate('Menu')),))
                        for state, title in panel_options:
                            with button(
                                    type='button',
                                    cls='vs-icon-button vs-panel-option%s' % (
                                        ' vs-button-active'
                                        if panel_state == state else ''),
                                    title=title,
                                    aria_label=title,
                                    aria_pressed=str(
                                        panel_state == state).lower(),
                                    data_panel_option=state,
                                    hx_post=ShellControl.url(action=(
                                        state
                                        if assistant_available
                                        else 'panel')),
                                    hx_target='#cassini',
                                    hx_swap='outerHTML'):
                                if state == 'none':
                                    fullscreen_icon()
                                elif state == 'menu':
                                    icon('menu')
                                else:
                                    icon('question')
                    img(
                        src='/cassini-private-images/logo.png',
                        alt='NaN-tic', cls='vs-header-logo',
                        data_seasonal_logo='true')
                    header_primary.add(GlobalSearch().tag())
                WorkspaceRenderer(self.engine.interface).tabs()
                with nav(cls='vs-user-nav', aria_label=translate('User')):
                    with div(
                            id='user-menu-host',
                            cls='vs-user-menu-host',
                            data_dismissible_popup_container='true'):
                        with button(
                                type='button',
                                cls='vs-user-menu-trigger',
                                aria_label=translate('User menu'),
                                aria_expanded=str(bool(shell_state.get(
                                        'user_menu'))).lower(),
                                hx_post=ShellControl.url(action='user'),
                                hx_target='#cassini',
                                hx_swap='outerHTML',
                                hx_sync='#user-menu-host:queue all'):
                            notification_count = Pool().get(
                                'res.notification').get_count()
                            if notification_count:
                                span(
                                    str(notification_count),
                                    cls='vs-notification-badge')
                            span(
                                user_status,
                                cls='vs-user-name', title=user_status)
                            icon('arrow-down')
                        if shell_state.get('user_menu'):
                            with ul(
                                    cls='vs-user-menu',
                                    role='menu',
                                    aria_label=translate('User and notifications'),
                                    data_dismissible_popup='remove'):
                                notifications = Pool().get(
                                    'res.notification').get()
                                if notifications:
                                    OpenNotification = Pool().get(
                                        'cassini.open.notification')
                                    for notification in notifications:
                                        with li(
                                                cls=(
                                                    'vs-notification-item'
                                                    + (
                                                        ' vs-notification-'
                                                        'unread'
                                                        if notification.get(
                                                            'unread')
                                                        else '')),
                                                role='none'):
                                            with button(
                                                    type='button',
                                                    role='menuitem',
                                                    hx_post=(
                                                        OpenNotification.url(
                                                            notification=(
                                                                notification[
                                                                    'id']))),
                                                    hx_target='#cassini',
                                                    hx_swap='outerHTML',
                                                    hx_push_url='true'):
                                                icon(
                                                    (notification.get('icon')
                                                     or
                                                     'tryton-notification')
                                                    .removeprefix(
                                                        'tryton-'))
                                                with div():
                                                    span(
                                                        notification.get(
                                                            'label') or
                                                        translate(
                                                            'Notification'),
                                                        cls=(
                                                            'vs-notification-'
                                                            'label'))
                                                    span(
                                                        notification.get(
                                                            'description')
                                                        or '',
                                                        cls=(
                                                            'vs-notification-'
                                                            'description'))
                                else:
                                    li(
                                        translate('No notifications at this time'),
                                        cls='vs-user-menu-empty',
                                        role='none')
                                with li(
                                        cls='vs-user-menu-actions',
                                        role='none'):
                                    with button(
                                            type='button',
                                            title=translate('All notifications'),
                                            aria_label=translate('All notifications'),
                                            role='menuitem',
                                            hx_post=Pool().get(
                                                'cassini.open.'
                                                'notifications').url(),
                                            hx_target='#cassini',
                                            hx_swap='outerHTML',
                                            hx_push_url='true'):
                                        icon('notification')
                                    with a(
                                            href=Demo.url(),
                                            title=translate('Demo'),
                                            aria_label=translate('Demo'),
                                            role='menuitem'):
                                        icon('public')
                                    with button(
                                            type='button',
                                            title=translate('Preferences'),
                                            aria_label=translate('Preferences'),
                                            role='menuitem',
                                            data_dismiss_popup_client='true',
                                            hx_get=Preferences.url(),
                                            hx_target='#modal',
                                            hx_swap='innerHTML'):
                                        icon('launch')
                                    with button(
                                            type='button',
                                            title=translate('Switch light/dark mode'),
                                            aria_label=(
                                                translate('Switch light/dark mode')),
                                            role='menuitem',
                                            hx_post=ShellControl.url(
                                                action='theme'),
                                            hx_target='#cassini',
                                            hx_swap='outerHTML'):
                                        theme_icon(
                                            shell_state.get(
                                                'theme') != 'dark')
                                    with a(
                                            href=Logout.url(),
                                            title=translate('Logout'),
                                            aria_label=translate('Logout'),
                                            role='menuitem',
                                            cls='vs-logout-action'):
                                        icon('exit')
                            button(
                                type='button', hidden=True,
                                data_dismissible_popup_sync='true',
                                hx_post=ShellControl.url(
                                    action='user-close'),
                                hx_swap='none',
                                hx_sync='#user-menu-host:queue all')
            with div(cls='vs-shell-layout'):
                with div(cls='vs-layout'):
                    if panel_state == 'menu':
                        aside(
                            Menu().tag(), id='main-menu',
                            cls='vs-sidebar')
                    elif panel_state == 'help':
                        aside(
                            HelpPanel().tag(),
                            id='help-sidebar',
                            cls='vs-sidebar vs-help-sidebar')
                    main(
                        WorkspaceRenderer(
                            self.engine.interface).render(
                                include_tabs=False),
                        cls='vs-main')
            with div(id='modal', cls='vs-modal-host') as modal:
                if preferences_content:
                    modal.add(preferences_content)
            div(id='notifications', cls='vs-notifications',
                aria_live='polite')
            self.version_changes_dialog()
        return app

    def render(self):
        login = self.require_user()
        if login:
            return login
        app = self.render_app()
        shell_state = self.engine.interface.component('shell')
        PageLayout = Pool().get('cassini.page.layout')
        layout = PageLayout(render=False)
        return layout.render_page(
            app, theme=shell_state.get('theme', 'light'))


class VersionChanges(SaoEndpoint):
    'Dismiss Cassini Version Changes'
    __name__ = 'cassini.version.changes'
    _url = '/version-changes/<int:update>/<string:action>'

    update = fields.Integer('Update')
    action = fields.Char('Action')

    @handle_endpoint_errors
    def render(self):
        Notification = optional_model('nantic_connection.notification')
        if not Notification:
            raise ValueError(translate(
                'Version changes require nantic_connection.'))
        if self.action not in {'accept', 'never'}:
            raise ValueError(translate('Unknown version change action'))
        updates = Notification.get_notifications([], [], 'version')
        update_ids = {int(update['id']) for update in updates}
        if int(self.update) not in update_ids:
            raise ValueError(translate('Unknown version change'))
        if self.action == 'never':
            Notification.set_has_read(
                Notification.browse([int(self.update)]), None, True)
        state = self.engine.interface.component(
            'version_changes', {'dismissed': []})
        dismissed = {
            int(notification_id)
            for notification_id in state.get('dismissed', [])
            }
        dismissed.add(int(self.update))
        state['dismissed'] = sorted(dismissed)
        self.engine.save()
        return html_response(div(
                id='version-changes-host',
                cls='vs-version-changes-host'))


class ShellControl(SaoEndpoint):
    'Update Cassini Shell State'
    __name__ = 'cassini.shell.control'
    _url = '/shell/<string:action>'

    action = fields.Char('Action')

    @handle_endpoint_errors
    def render(self):
        state = self.engine.interface.component('shell', {
                'panel': 'none',
                'theme': 'light',
                'user_menu': False,
                })
        panel = state.get('panel', 'none')
        if self.action == 'panel':
            states = (
                ['none', 'menu', 'help']
                if optional_model('nantic.chat.conversation')
                else ['none', 'menu'])
            state['panel'] = states[
                (states.index(panel) + 1) % len(states)
                if panel in states else 0]
        elif self.action == 'menu':
            state['panel'] = 'menu'
        elif self.action == 'help':
            state['panel'] = 'help'
        elif self.action == 'none':
            state['panel'] = 'none'
        elif self.action == 'theme':
            state['theme'] = (
                'dark' if state.get('theme', 'light') == 'light'
                else 'light')
            state['user_menu'] = False
        elif self.action == 'user':
            state['user_menu'] = not state.get('user_menu', False)
        elif self.action == 'user-close':
            state['user_menu'] = False
        elif self.action == 'fullscreen':
            state['panel'] = 'none'
        else:
            raise ValueError(translate('Unknown shell action'))
        self.engine.save()
        if self.action == 'user-close':
            return Response('', status=204)
        Shell = Pool().get('cassini.shell')
        return Shell(render=False).render_app()


class OpenNotification(SaoEndpoint):
    'Open a Tryton Notification'
    __name__ = 'cassini.open.notification'
    _url = '/notification/<int:notification>/open'

    notification = fields.Integer('Notification')

    @handle_endpoint_errors
    def render(self):
        Notification = Pool().get('res.notification')
        records = Notification.search([
                ('id', '=', self.notification),
                ('user', '=', Transaction().user),
                ], limit=1)
        if not records:
            raise ValueError(translate('Unknown notification'))
        notification, = records
        if notification.unread:
            Notification.mark_read([notification])

        opened = None
        action = notification._action_value
        if action:
            opened = self.engine.open_action(action)
        elif notification.model and notification.records:
            record_ids = json.loads(notification.records)
            action = {
                'id': None,
                'name': notification.label or notification.model,
                'type': 'ir.action.act_window',
                'res_model': notification.model,
                'res_id': record_ids[0] if len(record_ids) == 1 else None,
                'views': [],
                'domains': [],
                'pyson_domain': json.dumps([
                        ['id', 'in', record_ids]]),
                'pyson_context': '{}',
                'pyson_order': 'null',
                'pyson_search_value': '[]',
                'limit': 100,
                }
            opened = self.engine.open_action(action, {
                    'model': notification.model,
                    'id': record_ids[0] if len(record_ids) == 1 else None,
                    'ids': record_ids,
                    })
        self.engine.interface.component('shell', {})['user_menu'] = False
        self.engine.save()
        headers = {}
        if isinstance(opened, dict) and opened.get('id'):
            headers['HX-Push-Url'] = Pool().get(
                'cassini.activate.tab').url(tab=opened['id'])
        return html_response(
            Pool().get('cassini.shell')(render=False).render_app(),
            headers)


class OpenNotifications(SaoEndpoint):
    'Open All Tryton Notifications'
    __name__ = 'cassini.open.notifications'
    _url = '/notifications/open'

    @handle_endpoint_errors
    def render(self):
        action = {
            'id': None,
            'name': 'Notifications',
            'type': 'ir.action.act_window',
            'res_model': 'res.notification',
            'views': [],
            'domains': [],
            'pyson_domain': json.dumps([
                    ['user', '=', Transaction().user]]),
            'pyson_context': '{}',
            'pyson_order': json.dumps([['id', 'DESC']]),
            'pyson_search_value': '[]',
            'limit': 100,
            }
        tab = self.engine.open_action(action)
        self.engine.interface.component('shell', {})['user_menu'] = False
        self.engine.save()
        return html_response(
            Pool().get('cassini.shell')(render=False).render_app(),
            {'HX-Push-Url': Pool().get(
                    'cassini.activate.tab').url(tab=tab['id'])})


class HelpPanel(SaoEndpoint):
    'Cassini Help and Assistant Panel'
    __name__ = 'cassini.help.panel'
    _url = '/help'

    def render(self):
        new_state = (
            'assistant' not in self.engine.interface.data['components'])
        state = self.engine.interface.component('assistant', {
                'section': 'assistant',
                'conversation': None,
                'nan': None,
                'documentation_query': '',
                'documentation': None,
                'updates_filter': 'all',
                'update': None,
                })
        migrated_state = False
        if state.get('section') not in {
                'assistant', 'documentation', 'updates', 'tickets'}:
            state['section'] = 'assistant'
            migrated_state = True
        for key, value in (
                ('nan', None),
                ('documentation_query', ''),
                ('documentation', None),
                ('updates_filter', 'all'),
                ('update', None)):
            if key not in state:
                state[key] = value
                migrated_state = True
        if new_state or migrated_state:
            self.engine.save()
        conversation = self.conversation(state.get('conversation'))
        with section(
                id='help-panel', cls='vs-help-panel',
                data_speech_url=Pool().get(
                    'cassini.chat.speech').url(),
                data_transcribe_url=Pool().get(
                    'cassini.chat.transcribe').url()) as panel:
            with div(
                    id='help-accordion',
                    cls='vs-help-accordion',
                    role='tablist',
                    aria_multiselectable='false'):
                for identifier, title, image in (
                        ('assistant', translate('Assistant'), 'ai.svg'),
                        (
                            'documentation', translate('Documentation'),
                            'documentation-24px.svg'),
                        ('updates', translate('Updates'), 'update.svg'),
                        ('tickets', translate('Support'), 'form.svg')):
                    self.accordion_section(
                        identifier, title, image, state, conversation)
        return panel

    def accordion_section(
            self, identifier, title, image, state, conversation):
        HelpSection = Pool().get('cassini.help.section')
        opened = state.get('section') == identifier
        with article(
                cls='vs-help-accordion-panel%s' % (
                    ' vs-help-accordion-open' if opened else ''),
                data_help_section=identifier):
            with header(
                    cls='vs-help-accordion-heading',
                    role='tab'):
                with button(
                        type='button',
                        cls='vs-help-accordion-toggle',
                        aria_expanded=str(opened).lower(),
                        aria_controls='help-section-' + identifier,
                        hx_post=HelpSection.url(section=identifier),
                        hx_target='#help-panel',
                        hx_swap='outerHTML'):
                    img(
                        src=HELP_ICONS + image, alt='',
                        aria_hidden='true', cls='vs-help-section-icon')
                    span(title)
                    icon(
                        'arrow-down' if opened else 'arrow-right',
                        cls='vs-icon vs-help-accordion-arrow')
                if opened:
                    with div(cls='vs-help-heading-actions'):
                        self.section_actions(identifier, state, conversation)
            if opened:
                with div(
                        id='help-section-' + identifier,
                        cls='vs-help-accordion-body',
                        role='tabpanel'):
                    if identifier == 'assistant':
                        self.assistant_section(conversation, state)
                    elif identifier == 'documentation':
                        self.documentation_section(state)
                    elif identifier == 'updates':
                        self.updates_section(state)
                    else:
                        self.tickets_section()

    def section_actions(self, identifier, state, conversation):
        if identifier == 'assistant':
            ChatNew = Pool().get('cassini.chat.new')
            ChatSelect = Pool().get('cassini.chat.select')
            HelpResource = Pool().get('cassini.help.resource')
            Conversation = optional_model('nantic.chat.conversation')
            Agent = optional_model('nantic.agent')
            with form(
                    cls=(
                        'vs-help-heading-form '
                        'vs-new-conversation-group'),
                    hx_post=ChatNew.url(),
                    hx_target='#help-panel',
                    hx_swap='outerHTML'):
                with button(
                        type='submit',
                        cls=(
                            'vs-help-heading-button '
                            'vs-new-conversation-button'),
                        title=translate('New conversation'),
                        aria_label=translate('New conversation'),
                        disabled=not Conversation or None):
                    icon('create')
                if Agent:
                    agents = Agent.search([
                            ('available_as_nan', '=', True),
                            ('visible', '=', True),
                            ], order=[('name', 'ASC')])
                    default_label = translate('Default')
                    with details(
                            cls='vs-popup vs-nan-popup'):
                        with summary(
                                cls=(
                                    'vs-help-heading-button '
                                    'vs-nan-toggle'),
                                role='button',
                                title=translate('Start with a NaN'),
                                aria_label=translate('Choose a NaN')):
                            icon('arrow-down')
                        with div(
                                cls=(
                                    'vs-popup-menu '
                                    'vs-nan-popup-menu'),
                                role='menu',
                                aria_label=translate('NaNs')):
                            with button(
                                    default_label,
                                    type='button',
                                    role='menuitem',
                                    cls='vs-popup-item',
                                    hx_post=ChatNew.url(),
                                    hx_target='#help-panel',
                                    hx_swap='outerHTML'):
                                pass
                            for agent in agents:
                                with button(
                                        agent.name,
                                        type='button',
                                        role='menuitem',
                                        cls='vs-popup-item',
                                        hx_post=ChatNew.url(),
                                        hx_vals=json.dumps({
                                            'nan': agent.id}),
                                        hx_target='#help-panel',
                                        hx_swap='outerHTML'):
                                    pass
            if Conversation:
                conversations = Conversation.search([
                        ('create_uid', '=', Transaction().user),
                        ], order=[('write_date', 'DESC')], limit=20)
                with select(
                        name='conversation',
                        title=translate('Conversations'),
                        aria_label=translate('Conversations'),
                        cls='vs-conversation-select',
                        hx_post=ChatSelect.url(),
                        hx_trigger='change',
                        hx_target='#help-panel',
                        hx_swap='outerHTML',
                        hx_include='this'):
                    option(translate('Conversations'), value='')
                    for item in conversations:
                        option(
                            item.title or item.identifier,
                            value=item.identifier,
                            selected=(
                                item.identifier
                                == state.get('conversation')) or None)
                with button(
                        type='button',
                        cls='vs-help-heading-button',
                        title=translate('NaNs and goblins'),
                        aria_label=translate('NaNs and goblins'),
                        hx_post=HelpResource.url(resource='agents'),
                        hx_target='#workspace',
                        hx_swap='outerHTML',
                        hx_push_url='true'):
                    img(
                        src=HELP_ICONS + 'goblin.svg',
                        alt='', aria_hidden='true', cls='vs-icon')
        elif identifier == 'documentation':
            with a(
                    href=(
                        '/%s/documentation'
                        % Transaction().database.name),
                    target='_blank', rel='noopener',
                    cls='vs-help-heading-button',
                    title=translate('Open full documentation'),
                    aria_label=translate('Open full documentation')):
                icon('open')
        elif identifier == 'updates':
            HelpUpdates = Pool().get('cassini.help.updates')
            for filter_, image, title in (
                    ('unread', 'email-24px.svg',
                        translate('Unread updates')),
                    (
                        'all', 'hourglass_arrow_down-24px.svg',
                        translate('All updates'))):
                with button(
                        type='button',
                        cls='vs-help-heading-button%s' % (
                            ' vs-button-active'
                            if state.get('updates_filter') == filter_
                            else ''),
                        title=title, aria_label=title,
                        hx_post=HelpUpdates.url(filter=filter_),
                        hx_target='#help-panel',
                        hx_swap='outerHTML'):
                    img(
                        src=HELP_ICONS + image,
                        alt='', aria_hidden='true', cls='vs-icon')
        else:
            HelpResource = Pool().get('cassini.help.resource')
            with button(
                    type='button',
                    cls='vs-help-heading-button',
                    title=translate('Remote assistance'),
                    aria_label=translate('Remote assistance'),
                    data_help_cobrowse='true'):
                img(
                    src=HELP_ICONS + 'support_agent-24px.svg',
                    alt='', aria_hidden='true', cls='vs-icon')
            with button(
                    type='button',
                    cls='vs-help-heading-button',
                    title=translate('Open tickets'),
                    aria_label=translate('Open tickets'),
                    hx_post=HelpResource.url(resource='tickets'),
                    hx_target='#workspace',
                    hx_swap='outerHTML',
                    hx_push_url='true'):
                icon('open')

    def conversation(self, identifier):
        Conversation = optional_model('nantic.chat.conversation')
        if not Conversation or not identifier:
            return None
        records = Conversation.search([
                ('identifier', '=', identifier),
                ('create_uid', '=', Transaction().user),
                ], limit=1)
        return records[0] if records else None

    def assistant_section(self, conversation, state):
        Conversation = optional_model('nantic.chat.conversation')
        if not Conversation:
            p(
                translate('Install nantic_connection to enable the integrated '
                'assistant.'),
                cls='vs-notice')
        self.chat(conversation, state, bool(Conversation))

    def chat(self, conversation, state, enabled):
        ChatRequest = Pool().get('cassini.chat.request')
        ChatRefresh = Pool().get('cassini.chat.refresh')
        HelpResource = Pool().get('cassini.help.resource')
        with section(
                id='assistant-chat',
                cls='vs-chat',
                data_chat_poll_url=(
                    ChatRefresh.url()
                    if conversation and conversation.execution_state
                    else None)):
            with div(
                    id='chat-output',
                    cls='vs-chat-messages',
                    aria_live='polite'):
                Agent = optional_model('nantic.agent')
                if Agent and state.get('nan'):
                    agents = Agent.search([
                            ('id', '=', int(state['nan'])),
                            ('visible', '=', True),
                            ], limit=1)
                    if agents:
                        with div(cls='vs-nan-conversation-pill'):
                            strong(agents[0].name)
                if conversation:
                    for message in reversed(list(
                            reversed(conversation.messages))[-50:]):
                        if message.type not in {
                                'user', 'assistant', 'developer'}:
                            continue
                        with article(
                                cls='vs-chat-message vs-chat-'
                                + message.type,
                                aria_label=(
                                    translate('You')
                                    if message.type == 'user'
                                    else translate('Assistant'))):
                            div(
                                message.content or '',
                                cls='vs-chat-content',
                                data_chat_markdown='true')
                            if message.attachments:
                                with ul(cls='vs-chat-attachments'):
                                    for attachment in message.attachments:
                                        li(attachment.name)
                else:
                    p(
                        translate('Start a conversation. The active model, record, '
                        'selection, domain and language are sent as context.'),
                        cls='vs-muted')
                if conversation and conversation.execution_state:
                    div(
                        cls='vs-chat-working',
                        role='status',
                        aria_label=translate('Assistant is working'))
            if (conversation
                    and conversation.execution_state == 'wait_confirmation'):
                with div(cls='vs-chat-confirmation'):
                    p(translate('The assistant needs confirmation to continue.'))
                    for response, title in (
                            ('denied', translate('Deny')),
                            ('accepted', translate('Allow'))):
                        button(
                            title, type='button',
                            cls='vs-button%s' % (
                                ' vs-button-primary'
                                if response == 'accepted' else ''),
                            hx_post=ChatRequest.url(response=response),
                            hx_target='#help-panel',
                            hx_swap='outerHTML')
            with form(
                    cls='vs-chat-form',
                    enctype='multipart/form-data',
                    hx_post=ChatRequest.url(),
                    hx_encoding='multipart/form-data',
                    hx_target='#help-panel',
                    hx_swap='outerHTML',
                    data_chat_form='true'):
                input_(
                    type='file', name='attachments', multiple=True,
                    cls='vs-chat-file-input',
                    data_chat_files='true')
                div(
                    cls='vs-uploaded-files',
                    data_uploaded_files='true',
                    aria_live='polite')
                textarea(
                    id='message', name='content', rows=3,
                    placeholder=translate('Ask the assistant…'),
                    aria_label=translate('Message'),
                    disabled=not enabled or None,
                    cls='vs-chat-message-input')
                with div(cls='vs-chat-composer-actions'):
                    with div(cls='vs-chat-actions-left'):
                        for action, image, title in (
                                (
                                    'upload', 'upload-file.svg',
                                    translate('Attach files')),
                                (
                                    'capture', 'upload-screenshot.svg',
                                    translate('Attach screenshot')),
                                (
                                    'record', 'upload-record.svg',
                                    translate('Attach recording'))):
                            with button(
                                    type='button',
                                    cls='vs-chat-action',
                                    title=title, aria_label=title,
                                    disabled=not enabled or None,
                                    **{'data_help_' + action: 'true'}):
                                img(
                                    src=HELP_ICONS + image, alt='',
                                    aria_hidden='true', cls='vs-icon')
                        with button(
                                type='button',
                                cls='vs-chat-action',
                                title=translate('Toggle assistant voice'),
                                aria_label=translate('Toggle assistant voice'),
                                disabled=not enabled or None,
                                data_help_speech='true'):
                            img(
                                src=(
                                    HELP_ICONS
                                    + 'text_speech_shutdown.svg'),
                                alt='', aria_hidden='true',
                                cls='vs-icon')
                        with button(
                                type='button',
                                cls='vs-chat-action',
                                title=translate('Conversation artifacts'),
                                aria_label=translate('Conversation artifacts'),
                                disabled=(
                                    not enabled or not conversation or None),
                                hx_post=HelpResource.url(
                                    resource='artifacts'),
                                hx_target='#workspace',
                                hx_swap='outerHTML',
                                hx_push_url='true'):
                            img(
                                src=HELP_ICONS + 'artifacts.svg',
                                alt='', aria_hidden='true', cls='vs-icon')
                    with div(cls='vs-chat-actions-right'):
                        with button(
                                type='button',
                                cls='vs-chat-action',
                                title=translate('Speech to text'),
                                aria_label=translate('Speech to text'),
                                disabled=not enabled or None,
                                data_help_voice='true'):
                            img(
                                src=HELP_ICONS + 'mic.svg',
                                alt='', aria_hidden='true', cls='vs-icon')
                        with button(
                                type='submit',
                                cls='vs-chat-action vs-chat-send',
                                title=translate('Send'), aria_label=translate('Send'),
                                data_chat_send='true',
                                disabled=not enabled or None):
                            img(
                                src=HELP_ICONS + 'send.svg',
                                alt='', aria_hidden='true', cls='vs-icon')

    def documentation_section(self, state):
        Documentation = optional_model('nantic_connection.documentation')
        HelpDocumentation = Pool().get(
            'cassini.help.documentation')
        with form(
                cls='vs-help-documentation-search',
                hx_post=HelpDocumentation.url(action='search'),
                hx_target='#help-panel',
                hx_swap='outerHTML'):
            input_(
                type='search', name='query',
                id='help-documentation-search-input',
                value=state.get('documentation_query') or '',
                placeholder=translate('Search documentation…'),
                aria_label=translate('Search documentation'),
                cls='vs-input',
                hx_trigger='input changed delay:350ms',
                hx_post=HelpDocumentation.url(action='search'),
                hx_target='#help-panel',
                hx_swap='outerHTML',
                hx_sync='this:replace',
                hx_preserve='true',
                hx_include='this')
        if not Documentation:
            p(
                translate('Documentation is available when nantic_connection is '
                'installed.'),
                cls='vs-notice')
            return
        model = (
            self.engine.interface.active_tab.get('model')
            if self.engine.interface.active_tab else None)
        query = state.get('documentation_query') or ''
        documents = (
            Documentation.search_help_documents(
                query, model=model, limit=20)
            if query else Documentation.get_help_documents(model)[:20])
        selected = state.get('documentation')
        document = next((
                item for item in documents
                if str(item.get('id')) == str(selected)), None)
        if document:
            with article(cls='vs-help-document'):
                with button(
                        translate('Back'), type='button',
                        cls='vs-help-document-back',
                        hx_post=HelpDocumentation.url(action='back'),
                        hx_target='#help-panel',
                        hx_swap='outerHTML'):
                    pass
                h4(document.get('title') or translate('Documentation'))
                content = document.get('content_html')
                if isinstance(content, (bytes, bytearray)):
                    content = bytes(content).decode('utf-8')
                elif isinstance(content, list):
                    content = bytes(content).decode('utf-8')
                if content:
                    div(
                        raw(content),
                        cls='vs-help-document-content')
                else:
                    p(document.get('content') or document.get('excerpt') or '')
            return
        if not documents:
            p(translate('No documentation found.'), cls='vs-muted')
            return
        with div(cls='vs-help-document-list'):
            for document in documents:
                with button(
                        type='button',
                        cls='vs-help-document-result',
                        hx_post=HelpDocumentation.url(
                            action='open',
                            document=str(document.get('id'))),
                        hx_target='#help-panel',
                        hx_swap='outerHTML'):
                    strong(
                        document.get('title')
                        or translate('Documentation'))
                    span(
                        document.get('excerpt') or '',
                        cls='vs-muted')

    def updates_section(self, state):
        Notification = optional_model('nantic_connection.notification')
        HelpUpdates = Pool().get('cassini.help.updates')
        if not Notification:
            p(
                translate('Application updates are available when '
                'nantic_connection is installed.'),
                cls='vs-notice')
            return
        notifications = Notification.get_notifications(
            [], [], state.get('updates_filter') or 'all')
        selected = next((
                update for update in notifications
                if str(update.get('id')) == str(state.get('update'))), None)
        if selected:
            with button(
                    translate('Back'), type='button',
                    cls='vs-help-document-back',
                    hx_post=HelpUpdates.url(update=''),
                    hx_target='#help-panel',
                    hx_swap='outerHTML'):
                pass
            content = selected.get('notification_html')
            if isinstance(content, (bytes, bytearray)):
                content = bytes(content).decode('utf-8')
            elif isinstance(content, list):
                content = bytes(content).decode('utf-8')
            div(raw(content or ''), cls='vs-help-update-content')
            return
        if not notifications:
            p(translate('No updates available.'), cls='vs-muted')
            return
        with div(cls='vs-help-update-list'):
            for update in notifications:
                with button(
                        type='button',
                        cls='vs-help-update%s' % (
                            '' if update.get('has_read')
                            else ' vs-help-update-unread'),
                        hx_post=HelpUpdates.url(
                            update=update['id']),
                        hx_target='#help-panel',
                        hx_swap='outerHTML'):
                    strong(update.get('subject') or translate('Update'))
                    span(
                        str(update.get('datetime') or ''),
                        cls='vs-muted')

    def tickets_section(self):
        Ticket = optional_model('nantic.ticket')
        HelpResource = Pool().get('cassini.help.resource')
        if not Ticket:
            p(
                translate('Support tickets are available when nantic_connection is '
                'installed.'),
                cls='vs-notice')
            return
        try:
            tickets = Ticket.search([
                    ('users', 'in', [Transaction().user]),
                    ], order=[('id', 'DESC')], limit=20)
        except Exception:
            tickets = []
        p(
            translate('Track tickets created from the assistant and add comments '
            'without losing your current workspace.'),
            cls='vs-muted')
        if tickets:
            with ul(cls='vs-help-ticket-list'):
                for ticket in tickets:
                    li(ticket.rec_name)
        with button(
                translate('Open tickets'), type='button',
                cls='vs-button vs-button-primary',
                hx_post=HelpResource.url(resource='tickets'),
                hx_target='#workspace',
                hx_swap='outerHTML',
                hx_push_url='true'):
            pass


class HelpSection(SaoEndpoint):
    'Switch the Open Help Accordion Section'
    __name__ = 'cassini.help.section'
    _url = '/help/section/<string:section>'

    section = fields.Char('Section')

    @handle_endpoint_errors
    def render(self):
        if self.section not in {
                'assistant', 'documentation', 'updates', 'tickets'}:
            raise ValueError(translate('Unknown help section'))
        state = self.engine.interface.component('assistant', {})
        state['section'] = self.section
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class ChatRequest(SaoEndpoint):
    'Send a Request to Nantic Connection'
    __name__ = 'cassini.chat.request'
    _url = '/help/chat'

    content = fields.Text('Content')
    response = fields.Char('Response')

    @handle_endpoint_errors
    def render(self):
        Conversation = optional_model('nantic.chat.conversation')
        if not Conversation:
            raise ValueError('nantic_connection is not installed')
        state = self.engine.interface.component('assistant', {})
        identifier = state.get('conversation') or str(uuid.uuid4())
        conversations = Conversation.search([
                ('identifier', '=', identifier),
                ('create_uid', '=', Transaction().user),
                ], limit=1)
        if conversations:
            conversation, = conversations
        else:
            conversation = Conversation(identifier=identifier)
            conversation.save()
        tab = self.engine.interface.active_tab or {}
        selected = [
            tab.get('records', {}).get(key, {}).get('id')
            for key in tab.get('selected', [])
            ]
        selected = [record_id for record_id in selected if record_id]
        current = tab.get('records', {}).get(
            tab.get('current_record'), {}).get('id')
        metadata = {
            'company': Transaction().context.get('company'),
            'language': Transaction().language,
            'current_model': tab.get('model'),
            'current_record': current,
            'selected_records': selected,
            'domain': json.dumps(decode_value(
                    tab.get('domain', [])), default=str),
            'context': decode_value(tab.get('context', {})),
            }
        if state.get('nan'):
            metadata['nan_agent'] = int(state['nan'])
        attachments = []
        request = current_request()
        for uploaded in request.files.getlist('attachments')[:5]:
            data = uploaded.read()
            if not data:
                continue
            mimetype = (
                uploaded.mimetype
                or mimetypes.guess_type(uploaded.filename or '')[0]
                or 'application/octet-stream')
            attachments.append({
                    'name': uploaded.filename or 'attachment',
                    'data': 'data:%s;base64,%s' % (
                        mimetype,
                        base64.b64encode(data).decode('ascii')),
                    })
        body = {
            'conversation': identifier,
            'content': self.content or '',
            'type': 'text',
            'attachments': attachments,
            'metadata': metadata,
            }
        if self.response:
            body['response'] = self.response
        conversation.mark_assistant_messages_as_read()
        conversation.queue_request(body)
        state['conversation'] = identifier
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class ChatRefresh(SaoEndpoint):
    'Refresh the Nantic Connection Conversation'
    __name__ = 'cassini.chat.refresh'
    _url = '/help/chat/refresh'

    def render(self):
        return Pool().get('cassini.help.panel')().tag()


class ChatNew(SaoEndpoint):
    'Start a New Nantic Connection Conversation'
    __name__ = 'cassini.chat.new'
    _url = '/help/chat/new'

    nan = fields.Integer('NaN')

    def render(self):
        state = self.engine.interface.component('assistant', {})
        state.pop('conversation', None)
        state['nan'] = self.nan
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class ChatSelect(SaoEndpoint):
    'Select an Existing Assistant Conversation'
    __name__ = 'cassini.chat.select'
    _url = '/help/chat/select'

    conversation = fields.Char('Conversation')

    @handle_endpoint_errors
    def render(self):
        Conversation = optional_model('nantic.chat.conversation')
        if not Conversation:
            raise ValueError('nantic_connection is not installed')
        records = Conversation.search([
                ('identifier', '=', self.conversation),
                ('create_uid', '=', Transaction().user),
                ], limit=1)
        if self.conversation and not records:
            raise ValueError(translate('Unknown conversation'))
        state = self.engine.interface.component('assistant', {})
        if records:
            state['conversation'] = records[0].identifier
            agent = records[0].get_agent_info()
            state['nan'] = agent.get('id') if agent else None
        else:
            state.pop('conversation', None)
            state['nan'] = None
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class ChatTranscribe(SaoEndpoint):
    'Transcribe Assistant Audio Input'
    __name__ = 'cassini.chat.transcribe'
    _url = '/help/chat/transcribe'

    @handle_endpoint_errors
    def render(self):
        Token = optional_model('nantic_connection.token')
        request = current_request()
        uploaded = request.files.get('audio') if request else None
        if not Token or not uploaded:
            raise ValueError(translate('Speech recognition is not available'))
        text = Token.speech_to_text(uploaded.read()) or ''
        return Response(
            json.dumps({'text': text}),
            content_type='application/json')


class ChatSpeech(SaoEndpoint):
    'Read Assistant Text Aloud'
    __name__ = 'cassini.chat.speech'
    _url = '/help/chat/speech'

    text = fields.Text('Text')

    @handle_endpoint_errors
    def render(self):
        Token = optional_model('nantic_connection.token')
        if not Token:
            raise ValueError(translate('Text to speech is not available'))
        audio = Token.text_to_speech(self.text or '')
        if not audio:
            raise ValueError(translate('Text to speech did not return audio'))
        return Response(audio, content_type='audio/wav')


class HelpDocumentation(SaoEndpoint):
    'Search and Open Contextual Help Documentation'
    __name__ = 'cassini.help.documentation'
    _url = '/help/documentation/<string:action>'

    action = fields.Char('Action')
    query = fields.Char('Query')
    document = fields.Char('Document')

    @handle_endpoint_errors
    def render(self):
        state = self.engine.interface.component('assistant', {})
        state['section'] = 'documentation'
        if self.action == 'search':
            state['documentation_query'] = self.query or ''
            state['documentation'] = None
        elif self.action == 'open':
            state['documentation'] = self.document
        elif self.action == 'back':
            state['documentation'] = None
        else:
            raise ValueError(translate('Unknown documentation action'))
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class HelpUpdates(SaoEndpoint):
    'Filter and Open Help Updates'
    __name__ = 'cassini.help.updates'
    _url = '/help/updates'

    filter = fields.Char('Filter')
    update = fields.Char('Update')

    @handle_endpoint_errors
    def render(self):
        state = self.engine.interface.component('assistant', {})
        state['section'] = 'updates'
        if self.filter in {'all', 'unread'}:
            state['updates_filter'] = self.filter
            state['update'] = None
        if self.update is not None:
            state['update'] = self.update or None
            Notification = optional_model('nantic_connection.notification')
            if Notification and self.update:
                records = Notification.search([
                        ('id', '=', int(self.update)),
                        ], limit=1)
                if records:
                    Notification.set_has_read(records, None, True)
        self.engine.save()
        return Pool().get('cassini.help.panel')().tag()


class WizardHelp(SaoEndpoint):
    'Toggle and Navigate Contextual Wizard Help'
    __name__ = 'cassini.wizard.help'
    _url = '/tab/<string:tab>/wizard/help/<string:action>'

    tab = fields.Char('Tab')
    action = fields.Char('Action')
    filter = fields.Char('Filter')
    update = fields.Char('Update')

    @handle_endpoint_errors
    def render(self):
        engine = self.engine
        tab = engine.interface.get_tab(self.tab)
        if not tab or tab.get('kind') != 'wizard':
            raise ValueError(translate('Unknown tab'))
        if self.action == 'toggle':
            tab['wizard_help_open'] = not tab.get('wizard_help_open', False)
        elif self.action == 'filter':
            if self.filter not in {'all', 'unread'}:
                raise ValueError(translate('Unknown help section'))
            tab['wizard_help_filter'] = self.filter
            tab['wizard_help_update'] = None
        elif self.action == 'update':
            Notification = optional_model('nantic_connection.notification')
            if not Notification or not self.update:
                raise ValueError(translate('Unknown notification'))
            view = decode_value(tab.get('view', {}))
            view_ids = [view['view_id']] if view.get('view_id') else []
            notifications = Notification.get_notifications(
                view_ids, [tab.get('wizard_name')], 'all')
            if str(self.update) not in {
                    str(notification.get('id'))
                    for notification in notifications}:
                raise ValueError(translate('Unknown notification'))
            records = Notification.search([
                    ('id', '=', int(self.update)),
                    ], limit=1)
            if not records:
                raise ValueError(translate('Unknown notification'))
            Notification.set_has_read(records, None, True)
            tab['wizard_help_update'] = self.update
        elif self.action == 'back':
            tab['wizard_help_update'] = None
        else:
            raise ValueError(translate('Unknown help section'))
        engine.save()
        return workspace_response(engine)


class HelpResource(SaoEndpoint):
    'Open a Help Resource in the Workspace'
    __name__ = 'cassini.help.resource'
    _url = '/help/resource/<string:resource>'

    resource = fields.Char('Resource')

    @handle_endpoint_errors
    def render(self):
        resources = {
            'agents': (
                'nantic.agent', translate('NaNs and goblins'), []),
            'tickets': (
                'nantic.ticket', translate('Support tickets'),
                [['users', 'in', [Transaction().user]]]),
            'artifacts': (
                'nantic.chat.artifact',
                translate('Conversation artifacts'), None),
            }
        if self.resource not in resources:
            raise ValueError(translate('Unknown help resource'))
        model, title, domain = resources[self.resource]
        if not optional_model(model):
            raise ValueError(translate('This help resource is not installed'))
        if self.resource == 'artifacts':
            state = self.engine.interface.component('assistant', {})
            conversation = Pool().get(
                'cassini.help.panel')(render=False).conversation(
                    state.get('conversation'))
            if not conversation:
                raise ValueError(translate('Start or select a conversation first'))
            domain = [['conversation', '=', conversation.id]]
        action = {
            'id': None,
            'name': title,
            'type': 'ir.action.act_window',
            'res_model': model,
            'views': [],
            'domains': [],
            'pyson_domain': json.dumps(domain or []),
            'pyson_context': '{}',
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': 100,
            }
        tab = self.engine.open_action(action)
        return workspace_response(self.engine, {
                    'HX-Push-Url': Pool().get(
                        'cassini.activate.tab').url(tab=tab['id'])})


class Menu(SaoEndpoint):
    'Cassini Menu'
    __name__ = 'cassini.menu'
    _url = '/menu'

    def render(self):
        login = self.require_user()
        if login:
            return login
        MenuModel = Pool().get('ir.ui.menu')
        roots = MenuModel.search(
            [('parent', '=', None)], order=[('sequence', 'ASC')])
        new_menu_state = (
            'menu' not in self.engine.interface.data['components'])
        state = self.engine.interface.component('menu', {
                'expanded': [],
                })
        expanded = {
            int(menu_id) for menu_id in state.get('expanded', [])
            }
        Favorite = Pool().get('ir.ui.menu.favorite')
        favorite_ids = {
            favorite[0] for favorite in Favorite.get()
            }
        if new_menu_state:
            self.engine.save()
        with nav(
                id='menu-tree', cls='vs-menu vs-hierarchy',
                aria_label=translate('Tryton menu')) as menu:
            h2(translate('Menu'), cls='vs-menu-title')
            with ul(cls='vs-menu-list'):
                for root in roots:
                    self.menu_item(
                        root, expanded, favorite_ids, 0)
        return menu

    def menu_item(self, menu, expanded_ids, favorite_ids, depth):
        OpenMenu = Pool().get('cassini.open.menu')
        ToggleMenuItem = Pool().get('cassini.toggle.menu.item')
        ToggleMenuFavorite = Pool().get(
            'cassini.toggle.menu.favorite')
        children = list(menu.childs)
        expanded = menu.id in expanded_ids
        with li(
                cls='vs-menu-item%s' % (
                    ' vs-menu-item-expanded' if expanded else ''),
                data_menu=menu.id) as item:
            toggle = None
            if children:
                toggle = button(
                    type='button',
                    cls='vs-hierarchy-toggle vs-menu-toggle',
                    title=(
                        'Collapse ' + menu.name
                        if expanded else 'Expand ' + menu.name),
                    aria_label=(
                        'Collapse ' + menu.name
                        if expanded else 'Expand ' + menu.name),
                    aria_expanded=str(expanded).lower(),
                    hx_post=ToggleMenuItem.url(menu=menu.id),
                    hx_target='#menu-tree',
                    hx_swap='outerHTML')
                toggle.add(icon(
                        'arrow-down' if expanded else 'arrow-right'))
            with div(cls='vs-tree-content') as content:
                if menu.action_keywords:
                    with div(cls='vs-menu-entry'):
                        with button(
                                type='button',
                                cls='vs-menu-action vs-value',
                                title=menu.name,
                                hx_post=OpenMenu.url(menu=menu.id),
                                hx_target='#workspace',
                                hx_swap='outerHTML',
                                hx_push_url='true'):
                            with span(cls='vs-menu-item-label'):
                                if menu.icon:
                                    icon(
                                        menu.icon.removeprefix('tryton-'),
                                        cls='vs-icon vs-menu-item-icon')
                                span(menu.name)
                        favorite = menu.id in favorite_ids
                        with button(
                                type='button',
                                cls='vs-menu-favorite',
                                title=(
                                    translate('Remove from favorites')
                                    if favorite
                                    else translate('Add to favorites')),
                                aria_label=(
                                    translate(
                                        'Remove %(menu)s from favorites',
                                        menu=menu.name)
                                    if favorite
                                    else translate(
                                        'Add %(menu)s to favorites',
                                        menu=menu.name)),
                                hx_post=ToggleMenuFavorite.url(
                                    menu=menu.id,
                                    action='unset' if favorite else 'set'),
                                hx_target='#menu-tree',
                                hx_swap='outerHTML'):
                            icon(
                                'star' if favorite else 'star-border')
                elif children:
                    with button(
                            type='button',
                            cls='vs-menu-group vs-value',
                            title=menu.name,
                            aria_expanded=str(expanded).lower(),
                            hx_post=ToggleMenuItem.url(menu=menu.id),
                            hx_target='#menu-tree',
                            hx_swap='outerHTML'):
                        with span(cls='vs-menu-item-label'):
                            if menu.icon:
                                icon(
                                    menu.icon.removeprefix('tryton-'),
                                    cls='vs-icon vs-menu-item-icon')
                            span(menu.name)
                else:
                    with span(
                            cls='vs-menu-group vs-value',
                            title=menu.name):
                        with span(cls='vs-menu-item-label'):
                            if menu.icon:
                                icon(
                                    menu.icon.removeprefix('tryton-'),
                                    cls='vs-icon vs-menu-item-icon')
                            span(menu.name)
            item.add(HierarchyWidget.row(
                    content, toggle, depth, expanded,
                    extra_class='vs-menu-row'))
            if children and expanded:
                child_list = HierarchyWidget.children([])
                item.add(child_list)
                with child_list:
                    for child in children:
                        self.menu_item(
                            child, expanded_ids, favorite_ids, depth + 1)
        return item


class ToggleMenuItem(SaoEndpoint):
    'Toggle a Cassini Menu Branch'
    __name__ = 'cassini.toggle.menu.item'
    _url = '/menu/<int:menu>/toggle'

    menu = fields.Integer('Menu')

    @handle_endpoint_errors
    def render(self):
        MenuModel = Pool().get('ir.ui.menu')
        if not MenuModel.search([('id', '=', self.menu)], limit=1):
            raise ValueError(translate('Unknown menu item'))
        state = self.engine.interface.component('menu', {
                'expanded': [],
                })
        expanded = state.setdefault('expanded', [])
        if self.menu in expanded:
            expanded.remove(self.menu)
        else:
            expanded.append(self.menu)
        self.engine.save()
        return Pool().get('cassini.menu')().tag()


class ToggleMenuFavorite(SaoEndpoint):
    'Toggle a Cassini Menu Favorite'
    __name__ = 'cassini.toggle.menu.favorite'
    _url = '/menu/<int:menu>/favorite/<string:action>'

    menu = fields.Integer('Menu')
    action = fields.Char('Action')

    @handle_endpoint_errors
    def render(self):
        Menu = Pool().get('ir.ui.menu')
        Favorite = Pool().get('ir.ui.menu.favorite')
        records = Menu.search([
                ('id', '=', self.menu),
                ], limit=1)
        if not records or not records[0].action_keywords:
            raise ValueError(translate('Unknown menu action'))
        favorite_ids = {
            favorite[0] for favorite in Favorite.get()
            }
        if self.action == 'set' and self.menu not in favorite_ids:
            Favorite.set(self.menu)
        elif self.action == 'unset' and self.menu in favorite_ids:
            Favorite.unset(self.menu)
        elif self.action not in {'set', 'unset'}:
            raise ValueError(translate('Unknown favorite action'))
        return FragmentResponse.response([
                Fragment(
                    'menu-tree',
                    Pool().get('cassini.menu')().tag()),
                Fragment(
                    'global-search',
                    Pool().get(
                        'cassini.global.search')().tag()),
                Fragment(
                    'workspace',
                    WorkspaceRenderer(self.engine.interface).render(
                        include_tabs=False)),
                Fragment(
                    'workspace-tabs',
                    WorkspaceRenderer(self.engine.interface).tabs()),
                ])


class Demo(SaoEndpoint):
    'Cassini Stateful Component Demo'
    __name__ = 'cassini.demo'
    _url = '/demo'

    def render_demo(self):
        DemoUpdate = Pool().get('cassini.demo.update')
        Shell = Pool().get('cassini.shell')
        state = self.engine.interface.component('demo', {
                'title': 'A web made with server-owned components',
                'counter': 0,
                'tasks': [],
                'task_draft': '',
                })
        with main(
                id='demo-app',
                cls=(
                    'vs-demo-app min-h-screen bg-slate-50 text-slate-900 '
                    'dark:bg-slate-950 dark:text-slate-100')) as demo:
            with header(cls='vs-demo-header'):
                with div():
                    p(translate('Cassini state infrastructure'), cls='vs-eyebrow')
                    h1(state.get('title'))
                    p(
                        translate('This page uses no Tryton XML view. Dominate renders '
                        'its custom components, HTMX updates fragments and '
                        'the same workspace stores every draft.'),
                        cls='vs-muted')
                a(translate('Back to Sao'), href=Shell.url(), cls='vs-button')
            with section(cls='vs-demo-grid'):
                with article(cls='vs-demo-card'):
                    h2(translate('Persistent draft'))
                    label(
                        translate('Page title'), html_for='demo-title',
                        cls='vs-label')
                    input_(
                        id='demo-title', type='text', name='text',
                        value=state.get('title', ''),
                        cls='vs-input',
                        hx_post=DemoUpdate.url(action='title'),
                        hx_trigger='input changed delay:400ms',
                        hx_sync='this:replace',
                        hx_preserve='true',
                        hx_include='this',
                        hx_target='#demo-app',
                        hx_swap='none')
                    p(
                        translate('Reload now: the unfinished value stays here.'),
                        cls='vs-muted')
                with article(cls='vs-demo-card'):
                    h2(translate('Counter component'))
                    p(str(state.get('counter', 0)), cls='vs-demo-counter')
                    with div(cls='vs-dialog-actions'):
                        for action, title in (
                                ('decrement', '−'),
                                ('increment', '+')):
                            button(
                                title, type='button',
                                cls='vs-button',
                                aria_label=(
                                    translate('Decrement')
                                    if action == 'decrement'
                                    else translate('Increment')),
                                hx_post=DemoUpdate.url(action=action),
                                hx_target='#demo-app',
                                hx_swap='outerHTML')
                with article(cls='vs-demo-card vs-demo-tasks'):
                    h2(translate('Task component'))
                    with form(
                            cls='vs-demo-task-form',
                            hx_post=DemoUpdate.url(action='add'),
                            hx_target='#demo-app',
                            hx_swap='outerHTML'):
                        input_(
                            id='demo-task-input',
                            type='text', name='text',
                            value=state.get('task_draft', ''),
                            placeholder=translate('A new task'),
                            required=True, cls='vs-input',
                            hx_post=DemoUpdate.url(action='task-draft'),
                            hx_trigger='input changed delay:400ms',
                            hx_sync='this:replace',
                            hx_preserve='true',
                            hx_include='this',
                            hx_target='#demo-app',
                            hx_swap='none')
                        button(
                            translate('Add'), type='button',
                            cls='vs-button vs-button-primary',
                            hx_post=DemoUpdate.url(action='add'),
                            hx_target='#demo-app',
                            hx_swap='outerHTML')
                    with ul(cls='vs-demo-task-list'):
                        for task in state.get('tasks', []):
                            with li(
                                    cls='vs-demo-task%s' % (
                                        ' vs-demo-task-done'
                                        if task.get('done') else '')):
                                button(
                                    '✓' if task.get('done') else '○',
                                    type='button',
                                    cls='vs-link-button',
                                    aria_label=translate('Toggle task'),
                                    hx_post=DemoUpdate.url(
                                        action='toggle',
                                        task=task['id']),
                                    hx_target='#demo-app',
                                    hx_swap='outerHTML')
                                span(task.get('title', ''))
                                button(
                                    translate('Remove'), type='button',
                                    cls='vs-link-button',
                                    hx_post=DemoUpdate.url(
                                        action='remove',
                                        task=task['id']),
                                    hx_target='#demo-app',
                                    hx_swap='outerHTML')
                        if not state.get('tasks'):
                            li(translate('No tasks yet'), cls='vs-empty')
        return demo

    def render(self):
        login = self.require_user()
        if login:
            return login
        state = self.engine.interface.component('shell', {'theme': 'light'})
        if state.get('user_menu'):
            state['user_menu'] = False
            self.engine.save()
        PageLayout = Pool().get('cassini.page.layout')
        return PageLayout(render=False).render_page(
            self.render_demo(),
            'Component demo — Tryton',
            state.get('theme', 'light'))


class DemoUpdate(SaoEndpoint):
    'Update Cassini Component Demo'
    __name__ = 'cassini.demo.update'
    _url = '/demo/<string:action>'

    action = fields.Char('Action')
    text = fields.Char('Text')
    task = fields.Char('Task')

    @handle_endpoint_errors
    def render(self):
        state = self.engine.interface.component('demo', {
                'title': 'A web made with server-owned components',
                'counter': 0,
                'tasks': [],
                'task_draft': '',
                })
        if self.action == 'title':
            state['title'] = self.text or ''
        elif self.action == 'task-draft':
            state['task_draft'] = self.text or ''
        elif self.action == 'increment':
            state['counter'] = int(state.get('counter', 0)) + 1
        elif self.action == 'decrement':
            state['counter'] = int(state.get('counter', 0)) - 1
        elif self.action == 'add':
            title = (
                self.text or state.get('task_draft') or '').strip()
            if title:
                state.setdefault('tasks', []).append({
                        'id': uuid.uuid4().hex,
                        'title': title,
                        'done': False,
                        })
                state['task_draft'] = ''
        elif self.action in {'toggle', 'remove'}:
            tasks = state.setdefault('tasks', [])
            matching = next((
                    item for item in tasks
                    if item.get('id') == self.task), None)
            if not matching:
                raise ValueError(translate('Unknown demo task'))
            if self.action == 'toggle':
                matching['done'] = not matching.get('done', False)
            else:
                tasks.remove(matching)
        else:
            raise ValueError(translate('Unknown demo action'))
        self.engine.save()
        if self.action in {'title', 'task-draft'}:
            return Response('', status=204)
        return Pool().get('cassini.demo')(
            render=False).render_demo()


class GlobalSearch(SaoEndpoint):
    'Cassini Global Search'
    __name__ = 'cassini.global.search'
    _url = '/global-search'

    query = fields.Char('Query')

    def render_results(self):
        OpenMenu = Pool().get('cassini.open.menu')
        OpenResource = Pool().get('cassini.open.resource')
        results = []
        if self.query and self.session.system_user:
            Model = Pool().get('ir.model')
            results = Model.global_search(self.query, 20)
        with div(
                id='global-search-results',
                data_dismissible_popup='empty') as host:
            if self.query:
                with ul(cls='vs-search-results'):
                    for (
                            ratio, model, model_name,
                            id_, name, _icon_name) in results:
                        with li():
                            if model == 'ir.ui.menu':
                                endpoint = OpenMenu.url(menu=id_)
                            else:
                                endpoint = OpenResource.url(
                                    model=model, record=id_)
                            with button(
                                    type='button',
                                    cls='vs-search-result',
                                    data_global_search_result='true',
                                    hx_post=endpoint,
                                    hx_target='#workspace',
                                    hx_swap='outerHTML',
                                    hx_push_url='true'):
                                span(name, cls='vs-search-result-name')
                                span(
                                    model_name,
                                    cls='vs-search-result-model')
                    if not results:
                        li(translate('No results'), cls='vs-empty')
        return host

    def render(self):
        Favorite = Pool().get('ir.ui.menu.favorite')
        if optional_model('nantic.chat.conversation'):
            placeholder = translate(
                'Search 🔍︎ or chat with the assistant✦')
        else:
            placeholder = translate('Search 🔍︎')
        GlobalSearchResults = Pool().get(
            'cassini.global.search.results')
        with div(
                id='global-search', cls='vs-global-search',
                data_dismissible_popup_container='true') as search:
            with details(
                    cls='vs-popup vs-global-favorites-popup'):
                with summary(
                        cls='vs-global-favorites-toggle',
                        title=translate('Favorites'),
                        aria_label=translate('Favorites')):
                    icon('bookmarks')
                with div(
                        cls='vs-popup-menu',
                        role='menu',
                        aria_label=translate('Favorites')):
                    favorites = sorted(
                        Favorite.get(), key=lambda item: item[1])
                    if favorites:
                        for menu_id, name, _icon_name in favorites:
                            with button(
                                    type='button',
                                    cls='vs-popup-item',
                                    role='menuitem',
                                    hx_post=OpenMenu.url(menu=menu_id),
                                    hx_target='#workspace',
                                    hx_swap='outerHTML',
                                    hx_push_url='true'):
                                icon('star')
                                span(name)
                    else:
                        span(
                            translate('No favorites yet'),
                            cls='vs-popup-empty')
            with div(cls='vs-global-search-entry') as entry:
                input_(
                    type='search', name='query',
                    id='global-search-input',
                    value=self.query or '',
                    placeholder=placeholder,
                    aria_label=translate('Global search'),
                    autocomplete='off',
                    cls='vs-global-search-input',
                    hx_post=GlobalSearchResults.url(),
                    hx_trigger='input changed delay:300ms, search',
                    hx_target='#global-search-results',
                    hx_swap='outerHTML',
                    hx_sync='this:replace',
                    hx_preserve='true',
                    data_global_search_input='true',
                    data_global_search_assistant=(
                        'true'
                        if optional_model('nantic.chat.conversation')
                        else None),
                    hx_include='this')
                entry.add(self.render_results())
        return search


class GlobalSearchResults(SaoEndpoint):
    'Update Cassini Global Search Results'
    __name__ = 'cassini.global.search.results'
    _url = '/global-search/results'

    query = fields.Char('Query')

    def render(self):
        return GlobalSearch.render_results(self)


class OpenMenu(SaoEndpoint):
    'Open Cassini Menu'
    __name__ = 'cassini.open.menu'
    _url = '/open/menu/<int:menu>'

    menu = fields.Integer('Menu')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        tab = engine.open_menu(self.menu)
        if isinstance(tab, Response):
            return tab
        if tab is None:
            return html_response(
                Pool().get('cassini.shell')(
                    render=False).render_app())
        ActivateTab = Pool().get('cassini.activate.tab')
        return workspace_response(engine, {
                'HX-Push-Url': ActivateTab.url(tab=tab['id'])})


class OpenResource(SaoEndpoint):
    'Open Cassini Resource'
    __name__ = 'cassini.open.resource'
    _url = '/open/<string:model>/<int:record>'

    model = fields.Char('Model')
    record = fields.Integer('Record')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        tab = engine.open_resource(self.model, self.record)
        ActivateTab = Pool().get('cassini.activate.tab')
        return workspace_response(engine, {
                'HX-Push-Url': ActivateTab.url(tab=tab['id'])})


class OpenRelationRecord(SaoEndpoint):
    'Open a Cassini Relation Record in a Dialog'
    __name__ = 'cassini.open.relation.record'
    _url = (
        '/tab/<string:tab>/relation/'
        '<string:model>/<int:record>')

    tab = fields.Char('Tab')
    model = fields.Char('Model')
    record = fields.Integer('Record')
    source_record = fields.Char('Source Record')
    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        record_ids = None
        if self.source_record and self.field:
            (
                _tab, stored, _view, _renderer,
                _Parent, field, _endpoint,
                ) = relation_source(
                    engine, self.tab, self.source_record, self.field)
            if field._type in {'one2many', 'many2many'}:
                values = decode_value(stored.get('values', {}))
                record_ids = []
                for item in values.get(self.field) or []:
                    if isinstance(item, dict):
                        record_id = item.get('id')
                    elif str(item).lstrip('-').isdigit():
                        record_id = int(item)
                    else:
                        record_id = None
                    if record_id:
                        record_ids.append(record_id)
        engine.open_relation_modal(
            self.tab, self.model, self.record,
            record_ids=record_ids)
        return workspace_response(engine)


class OpenAction(SaoEndpoint):
    'Open Cassini Action'
    __name__ = 'cassini.open.action'
    _url = '/open/action/<int:action>'

    action = fields.Integer('Action')
    model = fields.Char('Model')
    record = fields.Integer('Record')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        data = {
            'model': self.model,
            'id': self.record,
            'ids': [self.record] if self.record else [],
            }
        engine = self.engine
        tab = engine.open_action(self.action, data)
        if isinstance(tab, Response):
            return tab
        if tab is None:
            return html_response(
                Pool().get('cassini.shell')(
                    render=False).render_app())
        ActivateTab = Pool().get('cassini.activate.tab')
        return workspace_response(engine, {
                'HX-Push-Url': ActivateTab.url(tab=tab['id'])})


class OpenRelated(SaoEndpoint):
    'Open Cassini Related Resource'
    __name__ = 'cassini.open.related'
    _url = '/tab/<string:tab>/related/<string:resource>'

    tab = fields.Char('Tab')
    resource = fields.Char('Resource')

    @handle_endpoint_errors
    def render(self):
        engine = self.engine
        related_tab = engine.open_related(
            self.tab, self.resource)
        if related_tab.get('relation_modal'):
            return workspace_response(engine)
        ActivateTab = Pool().get('cassini.activate.tab')
        return workspace_response(engine, {
                'HX-Push-Url': ActivateTab.url(
                    tab=related_tab['id'])})


class AttachmentUpload(SaoEndpoint):
    'Upload Cassini Attachments'
    __name__ = 'cassini.attachment.upload'
    _url = '/tab/<string:tab>/attachments/upload'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if not tab or tab.get('kind') != 'window':
            raise ValueError(translate('Unknown tab'))
        key = tab.get('current_record')
        record = tab.get('records', {}).get(key)
        if not record or not record.get('id'):
            raise ValueError(translate('Select a saved record first'))
        if (not tab.get('access', {}).get('write', True)
                or decode_value(tab.get('context', {})).get('_datetime')):
            raise ValueError(translate('This record is read-only'))
        request = current_request()
        uploads = (
            request.files.getlist('attachments') if request else [])
        values = []
        reference = '%s,%s' % (tab['model'], record['id'])
        for upload in uploads:
            if not upload or not upload.filename:
                continue
            values.append({
                    'name': upload.filename,
                    'type': 'data',
                    'data': upload.read(),
                    'resource': reference,
                    })
        if values:
            Attachment = Pool().get('ir.attachment')
            Attachment.create(values)
        return screen_response(self.engine, tab)


class AttachmentData(SaoEndpoint):
    'Read a Cassini Attachment'
    __name__ = 'cassini.attachment.data'
    _url = '/tab/<string:tab>/attachment/<int:attachment>/data'

    tab = fields.Char('Tab')
    attachment = fields.Integer('Attachment')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if not tab or tab.get('kind') != 'window':
            return Response('', status=404)
        key = tab.get('current_record')
        record = tab.get('records', {}).get(key)
        if not record or not record.get('id'):
            return Response('', status=404)
        Attachment = Pool().get('ir.attachment')
        attachments = Attachment.search([
                ('id', '=', self.attachment),
                ('resource', '=', '%s,%s' % (
                    tab['model'], record['id'])),
                ], limit=1)
        if not attachments or attachments[0].type != 'data':
            return Response('', status=404)
        attachment, = attachments
        content = attachment.data or b''
        content_type = (
            mimetypes.guess_type(attachment.name or '')[0]
            or 'application/octet-stream')
        filename = re.sub(r'[\r\n"]', '_', attachment.name or 'attachment')
        fallback_filename = (
            filename.encode('ascii', 'ignore').decode('ascii')
            or 'attachment')
        response = Response(content, content_type=content_type)
        response.headers['Content-Disposition'] = (
            "inline; filename=\"%s\"; filename*=UTF-8''%s" % (
                fallback_filename, quote(filename, safe='')))
        response.headers['Cache-Control'] = 'private, no-store'
        return response


class AttachmentPreview(SaoEndpoint):
    'Preview Cassini Attachments'
    __name__ = 'cassini.attachment.preview'
    _url = '/tab/<string:tab>/attachments/preview'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if not tab or tab.get('kind') != 'window':
            raise ValueError(translate('Unknown tab'))
        key = tab.get('current_record')
        record = tab.get('records', {}).get(key)
        if not record or not record.get('id'):
            raise ValueError(translate('Select a saved record first'))
        Attachment = Pool().get('ir.attachment')
        attachments = Attachment.search([
                ('resource', '=', '%s,%s' % (
                    tab['model'], record['id'])),
                ])
        title_id = 'attachment-preview-title-' + tab['id']
        with div(cls='vs-modal-backdrop') as backdrop:
            with section(
                    role='dialog', aria_modal='true',
                    aria_labelledby=title_id,
                    cls='vs-modal vs-attachment-preview-dialog'):
                h2(translate('Attachment preview'), id=title_id)
                with div(cls='vs-attachment-preview-list'):
                    if not attachments:
                        p(
                            translate('No attachments'),
                            cls='vs-popup-empty')
                    for attachment in attachments:
                        with article(cls='vs-attachment-preview-item'):
                            h4(attachment.name)
                            if attachment.type == 'link':
                                a(
                                    attachment.link,
                                    href=attachment.link,
                                    target='_blank',
                                    rel='noreferrer noopener')
                            else:
                                url = AttachmentData.url(
                                    tab=tab['id'],
                                    attachment=attachment.id)
                                content_type = (
                                    mimetypes.guess_type(
                                        attachment.name or '')[0] or '')
                                if content_type.startswith('image/'):
                                    img(
                                        src=url, alt=attachment.name,
                                        cls='vs-attachment-preview-image')
                                elif content_type == 'application/pdf':
                                    iframe(
                                        src=url,
                                        title=attachment.name,
                                        cls='vs-attachment-preview-frame')
                                else:
                                    a(
                                        translate('Open attachment'),
                                        href=url, target='_blank',
                                        rel='noreferrer noopener')
                with div(cls='vs-dialog-actions'):
                    button(
                        translate('Close'), type='button',
                        cls='vs-button', data_close_modal='true')
        return html_response(backdrop)


class ActivateTab(SaoEndpoint):
    'Activate Cassini Tab'
    __name__ = 'cassini.activate.tab'
    _url = '/tab/<string:tab>'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        engine.activate_tab(self.tab)
        if not is_htmx_request():
            Shell = Pool().get('cassini.shell')
            return Shell().tag()
        return workspace_response(engine, {
                'HX-Push-Url': Pool().get(
                    'cassini.activate.tab').url(tab=self.tab)})


class CloseTab(SaoEndpoint):
    'Close Cassini Tab'
    __name__ = 'cassini.close.tab'
    _url = '/tab/<string:tab>/close'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        tab = engine.interface.get_tab(self.tab)
        if has_unsaved_changes(tab):
            return unsaved_changes_response(
                engine, tab, 'close-tab')
        engine.close_tab(self.tab)
        return workspace_response(engine, {
                'HX-Push-Url': active_workspace_url(engine)})


class ResolveUnsavedChanges(SaoEndpoint):
    'Resolve Unsaved Changes before Leaving a Record'
    __name__ = 'cassini.resolve.unsaved.changes'
    _url = '/tab/<string:tab>/leave/<string:action>'

    tab = fields.Char('Tab')
    action = fields.Char('Action')
    decision = fields.Char('Decision')
    view = fields.Char('View')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        if self.action not in {
                'close-tab', 'new-record',
                'select-neighbor', 'switch-view', 'open-preferences'}:
            raise ValueError(translate('Unknown leave action'))
        if self.decision not in {'discard', 'save'}:
            raise ValueError(translate('Choose whether to save the changes'))
        engine = self.engine
        tab = engine.interface.get_tab(self.tab)
        if not tab:
            raise ValueError(translate('Unknown tab'))
        if self.decision == 'save':
            engine.save_records(self.tab)
        elif self.action not in {'close-tab', 'open-preferences'}:
            engine.revert_records(self.tab)

        headers = {}
        if self.action == 'close-tab':
            engine.close_tab(self.tab)
            headers['HX-Push-Url'] = active_workspace_url(engine)
        elif self.action == 'open-preferences':
            engine.close_tab(self.tab)
            Preferences = Pool().get('cassini.preferences')
            return Preferences(
                render=False).continue_after_closing_tabs(engine)
        elif self.action == 'new-record':
            engine.new_record(self.tab)
        elif self.action == 'select-neighbor':
            engine.select_neighbor(self.tab, self.direction)
        else:
            engine.switch_view(self.tab, self.view)

        return workspace_response(
            engine, headers, [Fragment(
                    'modal', div(id='modal', cls='vs-modal-host'))])


class SwitchView(SaoEndpoint):
    'Switch Cassini View'
    __name__ = 'cassini.switch.view'
    _url = '/tab/<string:tab>/view/<string:view>'

    tab = fields.Char('Tab')
    view = fields.Char('View')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if (self.view != tab.get('view_type')
                and has_unsaved_changes(tab, form_only=True)):
            return unsaved_changes_response(
                self.engine, tab, 'switch-view', {'view': self.view})
        self.engine.switch_view(self.tab, self.view)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SwitchDomain(SaoEndpoint):
    'Switch Cassini Domain'
    __name__ = 'cassini.switch.domain'
    _url = '/tab/<string:tab>/domain/<int:domain>'

    tab = fields.Char('Tab')
    domain = fields.Integer('Domain')

    @handle_endpoint_errors
    def render(self):
        self.engine.switch_domain(self.tab, self.domain)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SwitchPage(SaoEndpoint):
    'Switch Cassini Notebook Page'
    __name__ = 'cassini.switch.page'
    _url = (
        '/tab/<string:tab>/notebook/<string:notebook>/page/<int:page>')

    tab = fields.Char('Tab')
    notebook = fields.Char('Notebook')
    page = fields.Integer('Page')

    @handle_endpoint_errors
    def render(self):
        self.engine.switch_page(self.tab, self.notebook, self.page)
        tab = self.engine.interface.get_tab(self.tab)
        if tab.get('kind') == 'wizard':
            return ViewRenderer(self.engine.interface).wizard(tab)
        return screen_response(self.engine, tab)


class Search(SaoEndpoint):
    'Search Cassini View'
    __name__ = 'cassini.search'
    _url = '/tab/<string:tab>/search'

    tab = fields.Char('Tab')
    query = fields.Char('Query')

    @handle_endpoint_errors
    def render(self):
        filter_values = {}
        request = current_request()
        for key, value in (request.form.items() if request else []):
            if not key.startswith('filter__'):
                continue
            parts = key.split('__', 2)
            if len(parts) == 3:
                _prefix, name, mode = parts
                filter_values.setdefault(name, {})[mode] = value
        if filter_values:
            self.engine.advanced_search(
                self.tab, filter_values)
        else:
            self.engine.search(self.tab, self.query or '')
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SearchDraft(SaoEndpoint):
    'Update Cassini Search Draft'
    __name__ = 'cassini.search.draft'
    _url = '/tab/<string:tab>/search/draft'

    tab = fields.Char('Tab')
    query = fields.Char('Query')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.update_search_draft(
            self.tab, self.query or '')
        renderer = ViewRenderer(self.engine.interface)
        return FragmentResponse.response([
                Fragment(
                    'search-completion-' + tab['id'],
                    renderer.search_completion(tab)),
                Fragment(
                    'search-bookmark-control-' + tab['id'],
                    renderer.search_bookmark_control(tab)),
                ], stream=True)


class SearchBookmarkDialog(SaoEndpoint):
    'Create Cassini Search Bookmark Dialog'
    __name__ = 'cassini.search.bookmark.dialog'
    _url = '/tab/<string:tab>/search/bookmark'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if not tab or not decode_value(tab.get('search_domain', [])):
            raise ValueError(translate('Search for records before adding a bookmark'))
        SaveSearchBookmark = Pool().get(
            'cassini.save.search.bookmark')
        with div(cls='vs-modal-backdrop') as backdrop:
            with section(
                    role='dialog', aria_modal='true',
                    aria_labelledby='search-bookmark-title',
                    cls='vs-modal vs-bookmark-dialog'):
                h2(translate('Bookmark this filter'), id='search-bookmark-title')
                p(tab.get('search') or '', cls='vs-muted')
                with form(
                        hx_post=SaveSearchBookmark.url(tab=self.tab),
                        hx_target='#screen-' + self.tab,
                        hx_swap='outerHTML'):
                    with label(cls='vs-field'):
                        span(translate('Bookmark Name'))
                        input_(
                            type='text', name='name',
                            required=True, autofocus=True,
                            autocomplete='off', cls='vs-input')
                    with div(cls='vs-dialog-actions'):
                        button(
                            translate('Cancel'), type='button', cls='vs-button',
                            data_close_modal='true')
                        button(
                            translate('Save'), type='submit',
                            cls='vs-button vs-button-primary')
        return backdrop


class SaveSearchBookmark(SaoEndpoint):
    'Save Cassini Search Bookmark'
    __name__ = 'cassini.save.search.bookmark'
    _url = '/tab/<string:tab>/search/bookmark/save'

    tab = fields.Char('Tab')
    name = fields.Char('Name')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.add_search_bookmark(
            self.tab, self.name or '')
        return screen_and_close_modal_response(self.engine, tab)


class DeleteSearchBookmark(SaoEndpoint):
    'Delete Cassini Search Bookmark'
    __name__ = 'cassini.delete.search.bookmark'
    _url = '/tab/<string:tab>/search/bookmark/<int:bookmark>/delete'

    tab = fields.Char('Tab')
    bookmark = fields.Integer('Bookmark')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.remove_search_bookmark(
            self.tab, self.bookmark)
        return screen_response(self.engine, tab)


class ApplySearchBookmark(SaoEndpoint):
    'Apply Cassini Search Bookmark'
    __name__ = 'cassini.apply.search.bookmark'
    _url = '/tab/<string:tab>/search/bookmark/<int:bookmark>'

    tab = fields.Char('Tab')
    bookmark = fields.Integer('Bookmark')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.apply_search_bookmark(
            self.tab, self.bookmark)
        return screen_response(self.engine, tab)


class ToggleActive(SaoEndpoint):
    'Toggle Active Cassini Records'
    __name__ = 'cassini.toggle.active'
    _url = '/tab/<string:tab>/search/active'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        self.engine.toggle_active(self.tab)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class PageRecords(SaoEndpoint):
    'Page Cassini Records'
    __name__ = 'cassini.page.records'
    _url = '/tab/<string:tab>/page/<string:direction>'

    tab = fields.Char('Tab')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        self.engine.page(self.tab, self.direction)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class NavigateCalendar(SaoEndpoint):
    'Navigate Cassini Calendar'
    __name__ = 'cassini.navigate.calendar'
    _url = '/tab/<string:tab>/calendar/<string:direction>'

    tab = fields.Char('Tab')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        self.engine.navigate_calendar(self.tab, self.direction)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SetCalendarMode(SaoEndpoint):
    'Set Cassini Calendar Mode'
    __name__ = 'cassini.set.calendar.mode'
    _url = '/tab/<string:tab>/calendar/mode/<string:mode>'

    tab = fields.Char('Tab')
    mode = fields.Char('Mode')

    @handle_endpoint_errors
    def render(self):
        self.engine.set_calendar_mode(self.tab, self.mode)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class NewCalendarRecord(SaoEndpoint):
    'Create a Cassini Calendar Record'
    __name__ = 'cassini.new.calendar.record'
    _url = '/tab/<string:tab>/calendar/day/<string:day>/new'

    tab = fields.Char('Tab')
    day = fields.Char('Day')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(
            view.get('arch') or '<calendar/>')
        start = root.attrib.get('dtstart')
        definition = view.get('fields', {}).get(start, {})
        record = self.engine.new_record(self.tab)
        raw_value = date.fromisoformat(self.day)
        if definition.get('type') in {'datetime', 'timestamp'}:
            raw_value = datetime.combine(raw_value, time())
        if start:
            self.engine.update_field(
                self.tab, record['key'], start, raw_value)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class MoveCalendarRecord(SaoEndpoint):
    'Move a Cassini Calendar Record'
    __name__ = 'cassini.move.calendar.record'
    _url = (
        '/tab/<string:tab>/calendar/record/<string:record>/'
        'move/<string:direction>')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        self.engine.move_calendar_record(
            self.tab, self.record, self.direction)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SortRecords(SaoEndpoint):
    'Sort Cassini Records'
    __name__ = 'cassini.sort.records'
    _url = '/tab/<string:tab>/sort/<string:field>'

    tab = fields.Char('Tab')
    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        self.engine.sort(self.tab, self.field)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class ToggleColumn(SaoEndpoint):
    'Toggle Cassini Optional Column'
    __name__ = 'cassini.toggle.column'
    _url = '/tab/<string:tab>/column/<string:field>'

    tab = fields.Char('Tab')
    field = fields.Char('Field')
    visible = fields.Boolean('Visible')

    @handle_endpoint_errors
    def render(self):
        self.engine.toggle_column(
            self.tab, self.field, bool(self.visible))
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class ResizeTreeColumns(SaoEndpoint):
    'Resize Cassini Tree Columns'
    __name__ = 'cassini.resize.tree.columns'
    _url = '/tree/columns/width'

    model = fields.Char('Model')
    widths = fields.Text('Widths')
    screen_width = fields.Integer('Screen Width')

    @handle_endpoint_errors
    def render(self):
        Model = Pool().get(self.model)
        try:
            widths = json.loads(self.widths or '{}')
        except (TypeError, ValueError) as exception:
            raise ValueError(translate('Invalid column widths')) from exception
        if not isinstance(widths, dict) or len(widths) > 100:
            raise ValueError(translate('Invalid column widths'))
        normalized = {}
        for name, values in widths.items():
            if name not in Model._fields or not isinstance(values, list):
                raise ValueError(translate('Invalid column field'))
            if len(values) > 20:
                raise ValueError(translate('Invalid column occurrences'))
            normalized[name] = []
            for width in values:
                if width is None:
                    normalized[name].append(None)
                    continue
                if (
                        isinstance(width, bool)
                        or not isinstance(width, (int, float))
                        or not 24 <= width <= 4000):
                    raise ValueError(translate('Invalid column width'))
                normalized[name].append(round(width))
        screen_width = max(0, min(int(self.screen_width or 0), 10000))
        if normalized:
            ViewTreeWidth = Pool().get('ir.ui.view_tree_width')
            ViewTreeWidth.set_width(
                self.model, normalized, screen_width)
        self.engine.interface.data['screen_width'] = screen_width
        self.engine.save()
        return Response('', status=204)


class ToggleTreeNode(SaoEndpoint):
    'Toggle Cassini Tree Node'
    __name__ = 'cassini.toggle.tree.node'
    _url = '/tab/<string:tab>/tree/<string:record>/toggle'

    tab = fields.Char('Tab')
    record = fields.Char('Record')

    @handle_endpoint_errors
    def render(self):
        self.engine.toggle_tree_node(self.tab, self.record)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class MoveTreeRecord(SaoEndpoint):
    'Move a Cassini Tree Record'
    __name__ = 'cassini.move.tree.record'
    _url = (
        '/tab/<string:tab>/tree/<string:record>/move/<string:direction>')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        self.engine.move_tree_record(
            self.tab, self.record, self.direction)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class NewRecord(SaoEndpoint):
    'New Cassini Record'
    __name__ = 'cassini.new.record'
    _url = '/tab/<string:tab>/record/new'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if has_unsaved_changes(tab, form_only=True):
            return unsaved_changes_response(
                self.engine, tab, 'new-record')
        self.engine.new_record(self.tab)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SelectRecord(SaoEndpoint):
    'Select Cassini Record'
    __name__ = 'cassini.select.record'
    _url = '/tab/<string:tab>/record/<string:record>/select'

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    selected = fields.Boolean('Selected')
    row = fields.Boolean('Row')
    silent = fields.Boolean('Silent')
    open = fields.Boolean('Open')

    @handle_endpoint_errors
    def render(self):
        self.engine.select_record(
            self.tab, self.record,
            None if self.row else bool(self.selected))
        if self.silent and not self.open:
            return Response('', status=204)
        if self.open:
            tab = self.engine.interface.get_tab(self.tab)
            view = decode_value(tab.get('view', {}))
            root = ElementTree.fromstring(
                view.get('arch') or '<tree/>')
            if (root.attrib.get('keyword_open') in {'1', 'true'}
                    and tab['records'][self.record].get('id')):
                record_id = tab['records'][self.record]['id']
                ActionKeyword = Pool().get('ir.action.keyword')
                actions = ActionKeyword.get_keyword(
                    'tree_open', (tab['model'], record_id))
                if actions:
                    self.engine.open_action(actions[0], {
                            'model': tab['model'],
                            'id': record_id,
                            'ids': [record_id],
                            })
                    return workspace_response(self.engine, {
                            'HX-Push-Url': active_workspace_url(
                                self.engine)})
            if 'form' in tab.get('view_types', []):
                self.engine.switch_view(self.tab, 'form')
        tab = self.engine.interface.get_tab(self.tab)
        if self.row and not self.open:
            # The row and its checkbox are updated immediately in the
            # browser.  Only replace the toolbar so editable tree inputs keep
            # their focus while the record position is refreshed from the
            # authoritative server state.
            return html_response(
                ViewRenderer(self.engine.interface).toolbar(tab))
        return screen_response(self.engine, tab)


class SelectAllRecords(SaoEndpoint):
    'Select All Cassini Records'
    __name__ = 'cassini.select.all.records'
    _url = '/tab/<string:tab>/records/select'

    tab = fields.Char('Tab')
    selected = fields.Boolean('Selected')

    @handle_endpoint_errors
    def render(self):
        self.engine.select_all(self.tab, bool(self.selected))
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SelectNeighbor(SaoEndpoint):
    'Select Previous or Next Cassini Record'
    __name__ = 'cassini.select.neighbor'
    _url = '/tab/<string:tab>/record/<string:direction>'

    tab = fields.Char('Tab')
    direction = fields.Char('Direction')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if has_unsaved_changes(tab, form_only=True):
            return unsaved_changes_response(
                self.engine, tab, 'select-neighbor',
                {'direction': self.direction})
        self.engine.select_neighbor(self.tab, self.direction)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class RelationAutocomplete(SaoEndpoint):
    'Autocomplete a Cassini Relation'
    __name__ = 'cassini.relation.autocomplete'
    _url = (
        '/tab/<string:tab>/record/<string:record>/'
        'field/<string:field>/autocomplete')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')
    query = fields.Char('Query')

    @handle_endpoint_errors
    def render(self):
        (
            _tab, stored, view, renderer,
            _Parent, field, endpoint,
            ) = relation_source(
                self.engine, self.tab, self.record, self.field)
        query = (self.query or '').strip()
        definition = view['fields'][self.field]
        attributes = field_attributes(view, self.field)
        readonly = renderer.states(definition, attributes)[0]
        readonly = readonly or not renderer.editable
        ModelAccess = Pool().get('ir.model.access')
        relation_access = ModelAccess.get_access(
            [definition['relation']])[definition['relation']]
        if not relation_access['read']:
            raise ValueError(translate('This relation is not readable'))
        choices = (
            renderer.relation_choices(
                definition,
                text=query, limit=20)
            if query else [])
        create_allowed = (
            not readonly
            and relation_access['create']
            and str(attributes.get(
                    'create', '1')).lower()
            not in {'0', 'false', 'no'})
        field_id = dom_id(
            'field', self.tab, self.record, self.field)
        if field._type in {'one2many', 'many2many'}:
            values = decode_value(stored.get('values', {}))
            existing = {
                item.get('id') if isinstance(item, dict) else int(item)
                for item in (values.get(self.field) or [])
                if (isinstance(item, dict) and item.get('id'))
                or str(item).lstrip('-').isdigit()
                }
            choices = [
                choice for choice in choices
                if choice[0] not in existing]
            size = renderer.evaluate(attributes.get('size'))
            if (
                    isinstance(size, (int, float))
                    and not isinstance(size, bool)
                    and size >= 0
                    and len(existing) >= size):
                choices = []
                create_allowed = False
            return renderer.x2many_suggestions(
                field_id + '-suggestions',
                choices, self.field, field_id,
                can_create=create_allowed,
                open_=bool(query),
                modal_target=(
                    '#relation-modal'
                    if endpoint == 'preferences' else '#modal'),
                input_id=field_id + '-relation-input')
        return renderer.relation_suggestions(
            field_id + '-suggestions',
            choices,
            search_url=Pool().get('cassini.relation.search').url(
                tab=self.tab, record=self.record, field=self.field),
            new_url=(
                Pool().get('cassini.open.relation.new').url(
                    tab=self.tab, record=self.record, field=self.field)
                if create_allowed and endpoint != 'preferences' else None),
            open_=bool(query),
            modal_target=(
                '#relation-modal'
                if endpoint == 'preferences' else '#modal'))


class RelationSearch(SaoEndpoint):
    'Search and Select a Cassini Relation'
    __name__ = 'cassini.relation.search'
    _url = (
        '/tab/<string:tab>/record/<string:record>/'
        'field/<string:field>/search')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')
    query = fields.Char('Query')
    value = fields.Char('Value')
    column = fields.Char('Column')
    item = fields.Char('Item')
    visible = fields.Boolean('Visible')

    @handle_endpoint_errors
    def render(self):
        (
            tab, stored, view, renderer, _Parent, field, endpoint,
            ) = relation_source(
                self.engine, self.tab, self.record, self.field)
        definition = view['fields'][self.field]
        attributes = field_attributes(view, self.field)
        readonly = renderer.states(definition, attributes)[0]
        readonly = readonly or not renderer.editable
        Relation = Pool().get(definition['relation'])
        ModelAccess = Pool().get('ir.model.access')
        relation_access = ModelAccess.get_access(
            [definition['relation']])[definition['relation']]
        request = current_request()
        selected_values = (
            request.form.getlist('value')
            if request and request.method == 'POST' else [])
        if not selected_values and self.value:
            selected_values = [self.value]
        selected_ids = []
        for value in selected_values:
            if not str(value).lstrip('-').isdigit():
                raise ValueError(translate('Choose a related record'))
            selected_ids.append(int(value))

        if selected_ids:
            if readonly or not relation_access['read']:
                raise ValueError(translate('This relation field is read-only'))
            if field._type in {'many2one', 'one2one'}:
                relation_value = selected_ids[-1]
            else:
                values = decode_value(stored.get('values', {}))
                relation_values = list(values.get(self.field) or [])
                existing = {
                    item.get('id') if isinstance(item, dict) else int(item)
                    for item in relation_values
                    if (isinstance(item, dict) and item.get('id'))
                    or str(item).lstrip('-').isdigit()
                    }
                for relation_id in selected_ids:
                    if relation_id not in existing:
                        relation_values.append(relation_id)
                        existing.add(relation_id)
                relation_value = relation_values
            if endpoint == 'preferences':
                state, _changed = self.engine.update_preference(
                    view, self.field, relation_value)
                if field._type in {'one2many', 'many2many'}:
                    relation_id = selected_ids[-1]
                    x2many = state.setdefault(
                        'x2many', {}).setdefault(self.field, {
                            'view': 'tree',
                            'current': None,
                            'deleted': [],
                            })
                    x2many['current'] = str(relation_id)
                    x2many['deleted'] = [
                        item for item in x2many.setdefault('deleted', [])
                        if (
                            item.get('id')
                            if isinstance(item, dict) else item)
                        != relation_id]
                    self.engine.save()
                (
                    _tab, _stored, updated_view, updated_renderer,
                    _Parent, _field, _endpoint,
                    ) = relation_source(
                        self.engine, self.tab, self.record, self.field)
                return FragmentResponse.response([
                        Fragment(
                            dom_id(
                                'field', 'preferences',
                                str(Transaction().user), self.field),
                            updated_renderer.render(
                                self.field,
                                field_attributes(
                                    updated_view, self.field))),
                        Fragment(
                            'relation-modal',
                            div(
                                id='relation-modal',
                                cls='vs-nested-modal-host')),
                        ], all_out_of_band=True)
            if endpoint == 'wizard':
                (
                    tab, stored, _updated_view, _updated_renderer,
                    _Parent, _field, _endpoint,
                    ) = update_relation_source(
                        self.engine, self.tab, self.record,
                        self.field, view, endpoint, relation_value)
                if field._type in {'one2many', 'many2many'}:
                    relation_id = selected_ids[-1]
                    state = stored.setdefault(
                        'x2many', {}).setdefault(self.field, {
                            'view': 'tree',
                            'current': None,
                            'deleted': [],
                            })
                    state['current'] = str(relation_id)
                    state['deleted'] = [
                        item for item in state.setdefault('deleted', [])
                        if (
                            item.get('id')
                            if isinstance(item, dict) else item)
                        != relation_id]
                    self.engine.save()
                return workspace_response(
                    self.engine, extra_fragments=[Fragment(
                            'modal', div(
                                id='modal', cls='vs-modal-host'))])
            if field._type in {'many2one', 'one2one'}:
                self.engine.update_field(
                    self.tab, self.record, self.field,
                    str(relation_value), attributes)
            else:
                stored, _changed = self.engine.update_field(
                        self.tab, self.record, self.field,
                        relation_values, attributes)
                state = stored.setdefault(
                    'x2many', {}).setdefault(self.field, {
                        'view': 'tree',
                        'current': None,
                        'deleted': [],
                        })
                relation_id = selected_ids[-1]
                state['current'] = str(relation_id)
                state['deleted'] = [
                    item for item in state.setdefault('deleted', [])
                    if (
                        item.get('id') if isinstance(item, dict) else item)
                    != relation_id]
                self.engine.save()
            tab = self.engine.interface.get_tab(self.tab)
            return screen_and_close_modal_response(self.engine, tab)

        query = (self.query or '').strip()
        domain = renderer.relation_domain(definition)
        if query:
            record_ids = [
                value['id']
                for value in Relation.autocomplete(
                    query, domain, 100)
                if value.get('id')]
            records = Relation.browse(record_ids)
        else:
            records = Relation.search(domain, limit=100)
        if field._type in {'one2many', 'many2many'}:
            values = decode_value(stored.get('values', {}))
            existing = {
                item.get('id') if isinstance(item, dict) else int(item)
                for item in (values.get(self.field) or [])
                    if (isinstance(item, dict) and item.get('id'))
                    or str(item).lstrip('-').isdigit()
                    }
            records = [
                record for record in records if record.id not in existing]
        context = {}
        screen_width = tab.get('screen_width')
        if screen_width:
            context.update({
                    'screen_size': (int(screen_width), 0),
                    'view_tree_width': True,
                    })
        view_ids = [
            view_id.strip()
            for view_id in attributes.get('view_ids', '').split(',')]
        tree_view_id = (
            int(view_ids[0])
            if view_ids and view_ids[0].isdigit() else None)
        with Transaction().set_context(context):
            tree_view = Relation.fields_view_get(
                view_id=tree_view_id, view_type='tree')
        read_fields = WidgetRenderer.tree_read_fields(tree_view, Relation)
        rows = Relation.read(
            [record.id for record in records], read_fields) if records else []
        tree_records = {
            str(values['id']): {
                'key': str(values['id']),
                'id': values['id'],
                'values': values,
                'new': False,
                }
            for values in rows}
        search_state = stored.setdefault(
            'relation_search', {}).setdefault(self.field, {
                'column_visibility': {},
                })
        if self.column:
            if self.column not in Relation._fields:
                raise ValueError(translate('Unknown relation column'))
            search_state.setdefault(
                'column_visibility', {})[self.column] = bool(self.visible)
            self.engine.save()
        if self.item:
            if self.item not in tree_records:
                raise ValueError(translate('Unknown related record'))
            expanded = search_state.setdefault('expanded', [])
            if self.item in expanded:
                expanded.remove(self.item)
            else:
                expanded.append(self.item)
            self.engine.save()
        OpenRelationNew = Pool().get(
            'cassini.open.relation.new')
        RelationSearch = Pool().get(
            'cassini.relation.search')
        create_allowed = (
            endpoint != 'preferences'
            and not readonly
            and relation_access['create']
            and str(attributes.get(
                    'create', '1')).lower()
            not in {'0', 'false', 'no'})
        modal_target = (
            '#relation-modal'
            if endpoint == 'preferences' else '#modal')
        selection_target = (
            '#relation-modal'
            if endpoint == 'preferences'
            else '#workspace'
            if endpoint == 'wizard'
            else '#screen-' + tab['id'])
        multiple = field._type in {'one2many', 'many2many'}
        with div(cls='vs-modal-backdrop') as backdrop:
            with section(
                    role='dialog', aria_modal='true',
                    aria_labelledby='relation-search-title',
                    cls='vs-modal vs-relation-search-dialog'):
                h2(
                    translate(
                        'Search %(model)s',
                        model=(
                            definition.get('string')
                            or definition['relation'])),
                    id='relation-search-title')
                with div(cls='vs-search-toolbar'):
                    with form(
                            cls='vs-search-form vs-relation-search-form',
                            hx_get=RelationSearch.url(
                                tab=self.tab,
                                record=self.record,
                                field=self.field),
                            hx_target=modal_target,
                            hx_swap='innerHTML'):
                        input_(
                            type='search', name='query',
                            value=query, autofocus=True,
                            autocomplete='off', cls='vs-search-input',
                            placeholder=translate('Search records'))
                        with button(
                                type='submit',
                                cls='vs-icon-button',
                                title=translate('Search'), aria_label=translate('Search')):
                            icon('search')
                with form(
                        cls='vs-relation-selection-form',
                        hx_post=RelationSearch.url(
                            tab=self.tab,
                            record=self.record,
                            field=self.field),
                        hx_target=selection_target,
                        hx_swap='outerHTML') as selection_form:
                    tree_tab = {
                        'id': tab['id'],
                        'model': definition['relation'],
                        'records': tree_records,
                        'record_order': [str(record.id) for record in records],
                        'current_record': None,
                        'selected': [],
                        'expanded': search_state.setdefault('expanded', []),
                        'column_visibility': search_state.setdefault(
                            'column_visibility', {}),
                        'access': relation_access,
                        'context': tab.get('context', {}),
                        'screen_width': screen_width,
                        'empty_message': translate('No matching records'),
                        'relation_search_origin': {
                            'multiple': multiple,
                            'target': modal_target,
                            'url': RelationSearch.url(
                                tab=self.tab,
                                record=self.record,
                                field=self.field,
                                query=query),
                            },
                        }
                    selection_form.add(
                        ViewRenderer(None).tree(tree_tab, tree_view))
                    with div(cls='vs-dialog-actions'):
                        button(
                            translate('Cancel'), type='button', cls='vs-button',
                            data_close_relation_modal=(
                                'true'
                                if endpoint == 'preferences' else None),
                            data_close_modal=(
                                'true'
                                if endpoint != 'preferences' else None))
                        if create_allowed:
                            button(
                                translate('Create'), type='button',
                                cls='vs-button',
                                hx_post=OpenRelationNew.url(
                                    tab=self.tab,
                                    record=self.record,
                                    field=self.field),
                                hx_target='#workspace',
                                hx_swap='outerHTML')
                        button(
                            translate('OK'), type='submit',
                            cls='vs-button vs-button-primary',
                            disabled=True,
                            data_relation_search_confirm='true')
        return backdrop


class OpenRelationNew(SaoEndpoint):
    'Create a Record for a Cassini Relation'
    __name__ = 'cassini.open.relation.new'
    _url = (
        '/tab/<string:tab>/record/<string:record>/'
        'field/<string:field>/new')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')
    item = fields.Char('Item')
    query = fields.Char('Query')

    @handle_endpoint_errors
    def render(self):
        (
            parent, stored, view, renderer, Parent, field, endpoint,
            ) = relation_source(
                self.engine, self.tab, self.record, self.field)
        if endpoint not in {'record', 'wizard'}:
            raise ValueError(
                translate('Create the related record from its own window'))
        definition = view['fields'][self.field]
        attributes = field_attributes(view, self.field)
        relation = definition.get('relation')
        readonly = renderer.states(definition, attributes)[0]
        readonly = readonly or not renderer.editable
        ModelAccess = Pool().get('ir.model.access')
        access = ModelAccess.get_access([relation])[relation]
        if (
                readonly
                or not access['create']
                or str(attributes.get(
                        'create', '1')).lower()
                in {'0', 'false', 'no'}):
            raise ValueError(translate('Creating related records is not allowed'))
        draft_values = None
        if self.item:
            parent_values = (
                decode_value(parent.get('values', {}))
                if endpoint == 'wizard'
                else decode_value(stored.get('values', {})))
            relation_values = list(parent_values.get(self.field) or [])
            for index, item in enumerate(relation_values):
                if WidgetRenderer.x2many_item_key(item, index) != self.item:
                    continue
                if not isinstance(item, dict) or item.get('id'):
                    raise ValueError(
                        translate('The related record is already saved'))
                draft_values = decode_value(item.get('values', item))
                break
            else:
                raise ValueError(translate('Unknown related record'))
        view_ids = (
            [
                int(view_id) if view_id else None
                for view_id in attributes['view_ids'].split(',')]
            if attributes.get('view_ids') else [])
        if field._type in {'many2one', 'one2one'}:
            # Sao uses the configured tree view for the search window and
            # opens creation with the following form view, when present.
            form_view_ids = view_ids[1:]
            views = [(form_view_ids[0] if form_view_ids else None, 'form')]
        else:
            modes = [
                mode.strip()
                for mode in attributes.get('mode', 'tree,form').split(',')
                if mode.strip()]
            views = [
                (view_ids[index] if index < len(view_ids) else None, mode)
                for index, mode in enumerate(modes)]
        action = {
            'id': None,
            'name': definition.get('string') or relation,
            'type': 'ir.action.act_window',
            'res_model': relation,
            'views': views,
            'domains': [],
            'pyson_domain': '[]',
            'pyson_context': '{}',
            'pyson_order': 'null',
            'pyson_search_value': '[]',
            'limit': 100,
            }
        related = self.engine._open_window(
            action, {
                'model': parent['model'],
                'id': stored.get('id'),
                'ids': [
                    stored.get('id')]
                    if stored.get('id') else [],
                }, None, reuse=False)
        related['records'] = {}
        related['record_order'] = []
        related['selected'] = []
        related['current_record'] = None
        related['dirty'] = False
        related['relation_modal'] = True
        related['return_tab'] = parent['id']
        parent_id = stored.get('id')
        relation_field = (
            definition.get('relation_field')
            or getattr(field, 'field', None))
        context = decode_value(related.get('context', {}))
        for name, value in renderer.relation_defaults(definition).items():
            context['default_' + name] = value
        if self.query:
            Relation = Pool().get(relation)
            rec_name = Relation._rec_name
            if rec_name in Relation._fields:
                context.setdefault(
                    'default_' + rec_name, self.query.strip())
        if relation_field and parent_id:
            relation_parent_field = Pool().get(relation)._fields.get(
                relation_field)
            if (relation_parent_field
                    and relation_parent_field._type == 'reference'):
                context['default_' + relation_field] = '%s,%s' % (
                    parent['model'], parent_id)
            else:
                context['default_' + relation_field] = parent_id
        related['context'] = encode_value(context)
        related['exclude_field'] = relation_field
        related['relation_origin'] = {
            'tab': self.tab,
            'record': self.record,
            'field': self.field,
            'endpoint': endpoint,
            'item': self.item,
            }
        if draft_values is not None or (
                field._type == 'one2many' and not stored.get('id')):
            related['relation_draft'] = True
            related['relation_parent_field'] = relation_field
        relation_record = self.engine.new_record(related['id'])
        if draft_values is not None:
            values = decode_value(relation_record.get('values', {}))
            values.update(draft_values)
            relation_record['values'] = encode_value(values)
            relation_record['dirty'] = sorted(
                set(relation_record.get('dirty', [])) | set(draft_values))
            self.engine.save()
        return workspace_response(
            self.engine,
            extra_fragments=[Fragment(
                    'modal', div(id='modal', cls='vs-modal-host'))])


class X2ManyAction(SaoEndpoint):
    'Operate a Cassini One2Many or Many2Many Widget'
    __name__ = 'cassini.x2many.action'
    _url = (
        '/tab/<string:tab>/record/<string:record>/'
        'field/<string:field>/x2many/<string:action>')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')
    action = fields.Char('Action')
    item = fields.Char('Item')
    value = fields.Char('Value')

    @handle_endpoint_errors
    def render(self):
        (
            tab, stored, view, renderer, _Parent, field, endpoint,
            ) = relation_source(
                self.engine, self.tab, self.record, self.field)
        attributes = field_attributes(view, self.field)
        definition = view.get('fields', {}).get(self.field, {})
        readonly = renderer.states(definition, attributes)[0]
        readonly = readonly or not renderer.editable
        ModelAccess = Pool().get('ir.model.access')
        relation_access = ModelAccess.get_access(
            [definition.get('relation')])[definition.get('relation')]
        if self.action in {
                'delete', 'remove', 'undelete', 'add'}:
            if readonly:
                raise ValueError(translate('This relation field is read-only'))
            if (
                    self.action in {'delete', 'remove', 'undelete'}
                    and str(attributes.get(
                            'delete', '1')).lower()
                    in {'0', 'false', 'no'}):
                raise ValueError(translate('Removing related records is not allowed'))
            if self.action == 'delete' and field._type == 'one2many':
                if not relation_access['delete']:
                    raise ValueError(
                        translate('Deleting related records is not allowed'))
            if self.action == 'add' and not relation_access['read']:
                raise ValueError(translate('This relation is not readable'))
        values = decode_value(stored.get('values', {}))
        relation_values = list(values.get(self.field) or [])
        modes = (
            ['tree']
            if field._type == 'many2many' else [
                mode.strip() for mode in attributes.get(
                    'mode', 'tree,form').split(',')
                if mode.strip() in {'tree', 'form'}])
        if not modes:
            modes = ['tree']
        state = stored.setdefault(
            'x2many', {}).setdefault(self.field, {
                'view': modes[0],
                'current': None,
                'deleted': [],
                })
        deleted = state.setdefault('deleted', [])

        active = [
            (WidgetRenderer.x2many_item_key(value, index), value)
            for index, value in enumerate(relation_values)]
        removed = [
            (
                WidgetRenderer.x2many_item_key(
                    value, len(relation_values) + index),
                value)
            for index, value in enumerate(deleted)]
        all_items = active + removed
        keys = [key for key, value in all_items]
        current = state.get('current')
        if current not in keys:
            current = keys[0] if keys else None

        changed = {self.field}
        update_value = False
        if self.action == 'select':
            if self.item not in keys:
                raise ValueError(translate('Unknown related record'))
            current = self.item
        elif self.action == 'column':
            Relation = Pool().get(definition['relation'])
            if self.item not in Relation._fields:
                raise ValueError(translate('Unknown relation column'))
            visibility = state.setdefault('column_visibility', {})
            visibility[self.item] = not visibility.get(self.item, False)
        elif self.action == 'toggle':
            if self.item not in keys:
                raise ValueError(translate('Unknown related record'))
            expanded = state.setdefault('expanded', [])
            if self.item in expanded:
                expanded.remove(self.item)
            else:
                expanded.append(self.item)
        elif self.action in {'previous', 'next'}:
            if current:
                index = keys.index(current)
                index += -1 if self.action == 'previous' else 1
                index = max(0, min(index, len(keys) - 1))
                current = keys[index]
        elif self.action == 'switch':
            if len(modes) > 1:
                current_view = state.get('view', modes[0])
                state['view'] = modes[
                    (modes.index(current_view) + 1) % len(modes)]
        elif self.action in {'delete', 'remove'}:
            match = next((
                    (index, value)
                    for index, (key, value) in enumerate(active)
                    if key == current), None)
            if match:
                index, value = match
                relation_values.pop(index)
                if isinstance(value, dict) and not value.get('id'):
                    current = None
                else:
                    deleted.append(value)
                update_value = True
        elif self.action == 'undelete':
            match = next((
                    (index, value)
                    for index, (key, value) in enumerate(removed)
                    if key == current), None)
            if match is None and removed:
                match = (len(removed) - 1, removed[-1][1])
            if match:
                index, value = match
                deleted.pop(index)
                relation_values.append(value)
                current = WidgetRenderer.x2many_item_key(
                    value, len(relation_values) - 1)
                update_value = True
        elif self.action == 'add':
            if not self.value or not str(self.value).lstrip('-').isdigit():
                raise ValueError(translate('Choose a related record to add'))
            record_id = int(self.value)
            existing_ids = {
                item.get('id') if isinstance(item, dict) else int(item)
                for item in relation_values
                if (isinstance(item, dict) and item.get('id'))
                or str(item).lstrip('-').isdigit()
                }
            if record_id not in existing_ids:
                deleted[:] = [
                    item for item in deleted
                    if not (
                        (item.get('id') if isinstance(item, dict) else item)
                        == record_id)]
                relation_values.append(record_id)
                update_value = True
            current = str(record_id)
        else:
            raise ValueError(translate('Unknown x2many action'))

        state['current'] = current
        if update_value:
            (
                tab, stored, view, renderer,
                _Parent, _field, endpoint,
                ) = update_relation_source(
                    self.engine, self.tab, self.record,
                    self.field, view, endpoint, relation_values)
            if endpoint == 'record':
                stored_values = decode_value(stored.get('values', {}))
                stored_values[self.field] = relation_values
                stored['values'] = encode_value(stored_values)
            elif endpoint == 'wizard':
                stored_values = decode_value(tab.get('values', {}))
                stored_values[self.field] = relation_values
                tab['values'] = encode_value(stored_values)
            else:
                preference_state = self.engine.interface.component(
                    'preferences')
                stored_values = decode_value(
                    preference_state.get('values', {}))
                stored_values[self.field] = relation_values
                preference_state['values'] = encode_value(stored_values)
            self.engine.save()
            changed = {self.field}
        else:
            self.engine.save()

        (
            tab, stored, view, renderer,
            _Parent, _field, endpoint,
            ) = relation_source(
                self.engine, self.tab, self.record, self.field)
        visible_changed = [
            name for name in changed
            if name in view.get('fields', {})]
        if self.field in visible_changed:
            visible_changed.remove(self.field)
        visible_changed.insert(0, self.field)
        fragments = [
            Fragment(
                dom_id('field', self.tab, self.record, name),
                renderer.render(name, field_attributes(view, name)))
            for name in visible_changed
            ]
        if endpoint == 'record':
            fragments.append(Fragment(
                    'toolbar-' + self.tab,
                    ViewRenderer(self.engine.interface).toolbar(tab)))
            fragments.append(Fragment(
                    'workspace-tabs',
                    WorkspaceRenderer(self.engine.interface).tabs()))
        return FragmentResponse.response(
            fragments, stream=len(fragments) > 2)


class UpdateField(SaoEndpoint):
    'Update Cassini Field'
    __name__ = 'cassini.update.field'
    _url = (
        '/tab/<string:tab>/record/<string:record>/field/<string:field>')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')
    value = fields.Char('Value')

    @handle_endpoint_errors
    def render(self):
        request = current_request()
        uploaded = request.files.get('value') if request else None
        if uploaded:
            stored, changed = self.engine.update_binary(
                self.tab, self.record, self.field, uploaded.read())
        else:
            tab = self.engine.interface.get_tab(self.tab)
            view = decode_value(tab['view'])
            definition = view.get('fields', {}).get(self.field, {})
            raw_values = request.form.getlist('value')
            raw_value = (
                raw_values
                if definition.get('type') in {
                    'many2many', 'one2many', 'multiselection'}
                else self.value)
            stored, changed = self.engine.update_field(
                self.tab, self.record, self.field, raw_value,
                field_attributes(view, self.field))
        tab = self.engine.interface.get_tab(self.tab)
        view_definition = self.engine.interface.get_tab(self.tab)['view']
        view_definition = decode_value(view_definition)
        renderer = WidgetRenderer(tab, stored, view_definition)
        visible_changed = [
            name for name in changed
            if name in view_definition.get('fields', {})
            ]
        attributes = field_attributes(view_definition, self.field)
        widget = (
            attributes.get('widget')
            or view_definition.get(
                'fields', {}).get(self.field, {}).get('type', 'char'))
        preserve_self = widget in (
            WidgetRenderer.text_widgets
            | WidgetRenderer.textarea_widgets
            | WidgetRenderer.numeric_widgets
            | WidgetRenderer.date_widgets)
        if preserve_self:
            if self.field in visible_changed:
                visible_changed.remove(self.field)
        else:
            if self.field in visible_changed:
                visible_changed.remove(self.field)
            visible_changed.insert(0, self.field)
        fragments = []
        for name in visible_changed:
            target = dom_id(
                'field', self.tab, self.record, name)
            fragments.append(Fragment(
                    target,
                    renderer.render(
                        name, field_attributes(view_definition, name))))
        notices = decode_value(tab.get('notice', []))
        if notices:
            with div(
                    id='notifications', cls='vs-notifications',
                    aria_live='polite') as host:
                for level, message in notices:
                    div(
                        message,
                        cls='vs-notice vs-notice-' + level,
                        role='status')
            fragments.append(Fragment('notifications', host))
        fragments.append(Fragment(
                'toolbar-' + self.tab,
                ViewRenderer(self.engine.interface).toolbar(tab)))
        fragments.append(Fragment(
                'workspace-tabs',
                WorkspaceRenderer(self.engine.interface).tabs()))
        return FragmentResponse.response(
            fragments,
            stream=len(fragments) > 2,
            all_out_of_band=True)


class ScanCode(SaoEndpoint):
    'Scan a Code into a Cassini Form'
    __name__ = 'cassini.scan.code'
    _url = '/tab/<string:tab>/record/<string:record>/scan'

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    code = fields.Char('Code')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        view = decode_value(tab.get('view', {}))
        root = ElementTree.fromstring(
            view.get('arch') or '<form/>')
        self.engine.scan_code(
            self.tab, self.record, self.code or '')
        if root.attrib.get('scan_code') == 'submit':
            self.engine.save_record(self.tab, self.record)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SaveRecord(SaoEndpoint):
    'Save Cassini Record'
    __name__ = 'cassini.save.record'
    _url = '/tab/<string:tab>/record/<string:record>/save'

    tab = fields.Char('Tab')
    record = fields.Char('Record')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if tab and tab.get('relation_draft'):
            self.engine.save_relation_draft(self.tab)
            return workspace_response(
                self.engine, {
                    'HX-Push-Url': active_workspace_url(self.engine),
                    }, [Fragment(
                        'modal', div(
                            id='modal', cls='vs-modal-host'))],
                all_out_of_band=True)
        relation_modal = bool(tab and tab.get('relation_modal'))
        return_tab = tab.get('return_tab') if relation_modal else None
        self.engine.save_record(self.tab, self.record)
        if relation_modal:
            self.engine.close_tab(self.tab)
            if self.engine.interface.get_tab(return_tab):
                self.engine.activate_tab(return_tab)
            return workspace_response(
                self.engine, {
                    'HX-Push-Url': active_workspace_url(self.engine),
                    }, [Fragment(
                        'modal', div(
                            id='modal', cls='vs-modal-host'))],
                all_out_of_band=True)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class SaveRecords(SaoEndpoint):
    'Save Cassini Records'
    __name__ = 'cassini.save.records'
    _url = '/tab/<string:tab>/records/save'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        if tab and tab.get('relation_draft'):
            self.engine.save_relation_draft(self.tab)
            return workspace_response(
                self.engine, {
                    'HX-Push-Url': active_workspace_url(self.engine),
                    }, [Fragment(
                        'modal', div(
                            id='modal', cls='vs-modal-host'))],
                all_out_of_band=True)
        relation_modal = bool(tab and tab.get('relation_modal'))
        return_tab = tab.get('return_tab') if relation_modal else None
        self.engine.save_records(self.tab)
        if relation_modal:
            self.engine.close_tab(self.tab)
            if self.engine.interface.get_tab(return_tab):
                self.engine.activate_tab(return_tab)
            return workspace_response(
                self.engine, {
                    'HX-Push-Url': active_workspace_url(self.engine),
                    }, [Fragment(
                        'modal', div(
                            id='modal', cls='vs-modal-host'))],
                all_out_of_band=True)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class DeleteRecord(SaoEndpoint):
    'Delete Cassini Record'
    __name__ = 'cassini.delete.record'
    _url = '/tab/<string:tab>/record/<string:record>/delete'

    tab = fields.Char('Tab')
    record = fields.Char('Record')

    @handle_endpoint_errors
    def render(self):
        self.engine.delete_record(self.tab, self.record)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class DeleteRecords(SaoEndpoint):
    'Delete Cassini Records'
    __name__ = 'cassini.delete.records'
    _url = '/tab/<string:tab>/records/delete'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        self.engine.delete_records(self.tab)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class RevertRecord(SaoEndpoint):
    'Revert Cassini Record'
    __name__ = 'cassini.revert.record'
    _url = '/tab/<string:tab>/record/<string:record>/revert'

    tab = fields.Char('Tab')
    record = fields.Char('Record')

    @handle_endpoint_errors
    def render(self):
        self.engine.revert_record(self.tab, self.record)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class DuplicateRecord(SaoEndpoint):
    'Duplicate Cassini Record'
    __name__ = 'cassini.duplicate.record'
    _url = '/tab/<string:tab>/duplicate'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        self.engine.duplicate(self.tab)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class ReloadTab(SaoEndpoint):
    'Reload Cassini Tab'
    __name__ = 'cassini.reload.tab'
    _url = '/tab/<string:tab>/reload'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        self.engine.reload_tab(self.tab)
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class RunButton(SaoEndpoint):
    'Run Cassini Button'
    __name__ = 'cassini.run.button'
    _url = '/tab/<string:tab>/button/<string:button>'

    tab = fields.Char('Tab')
    button = fields.Char('Button')
    kind = fields.Char('Kind')
    record = fields.Char('Record')

    @handle_endpoint_errors
    def render(self):
        engine = self.engine
        engine.run_button(
            self.tab, self.button, self.kind or 'class', self.record)
        return workspace_response(engine, {
                'HX-Push-Url': active_workspace_url(engine)})


class RunToolbarAction(SaoEndpoint):
    'Run Cassini Toolbar Action'
    __name__ = 'cassini.toolbar.action'
    _url = '/tab/<string:tab>/action/<int:action>'

    tab = fields.Char('Tab')
    action = fields.Integer('Action')

    @handle_endpoint_errors
    def render(self):
        engine = self.engine
        response = engine.toolbar_action(self.tab, self.action)
        if isinstance(response, dict) and response.get('report_key'):
            ReportDownload = Pool().get('cassini.report.download')
            return workspace_response(engine, {
                    'HX-Trigger': json.dumps({
                            'voyager-download': {
                                'urls': [ReportDownload.url(
                                        key=response['report_key'])],
                                },
                            }),
                    })
        if isinstance(response, Response):
            return response
        return workspace_response(engine, {
                'HX-Push-Url': active_workspace_url(engine)})


class ExportRecords(SaoEndpoint):
    'Export Cassini Records'
    __name__ = 'cassini.export.records'
    _url = '/tab/<string:tab>/export'

    tab = fields.Char('Tab')
    export_id = fields.Integer('Export')

    @handle_endpoint_errors
    def render(self):
        return self.engine.export(self.tab, self.export_id)


class ImportRecords(SaoEndpoint):
    'Import Cassini Records'
    __name__ = 'cassini.import.records'
    _url = '/tab/<string:tab>/import'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        request = current_request()
        uploaded = request.files.get('file') if request else None
        if not uploaded or not uploaded.filename:
            raise ValueError(translate('Choose a CSV file to import'))
        self.engine.import_csv(self.tab, uploaded.read())
        tab = self.engine.interface.get_tab(self.tab)
        return screen_response(self.engine, tab)


class ShowRevisions(SaoEndpoint):
    'Show Cassini Revisions'
    __name__ = 'cassini.show.revisions'
    _url = '/tab/<string:tab>/revisions'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.revisions(self.tab)
        return revision_dialog(tab)


class CloseRevisions(SaoEndpoint):
    'Close Cassini Revisions'
    __name__ = 'cassini.close.revisions'
    _url = '/tab/<string:tab>/revisions/close'

    tab = fields.Char('Tab')

    @handle_endpoint_errors
    def render(self):
        self.engine.close_revisions(self.tab)
        return Response('', content_type='text/html')


class SetRevision(SaoEndpoint):
    'Set Cassini Revision'
    __name__ = 'cassini.set.revision'
    _url = '/tab/<string:tab>/revision/<string:revision>'

    tab = fields.Char('Tab')
    revision = fields.Char('Revision')

    @handle_endpoint_errors
    def render(self):
        index = (
            None if self.revision == 'current'
            else int(self.revision))
        self.engine.set_revision(self.tab, index)
        empty_modal = div(id='modal', cls='vs-modal-host')
        return workspace_response(
            self.engine,
            extra_fragments=[Fragment('modal', empty_modal)])


class Preferences(SaoEndpoint):
    'Cassini Preferences'
    __name__ = 'cassini.preferences'
    _url = '/preferences'

    def close_tabs_confirmation(self):
        with div(cls='vs-modal-backdrop') as backdrop:
            with section(
                    role='alertdialog', aria_modal='true',
                    aria_labelledby='close-tabs-title',
                    aria_describedby='close-tabs-description',
                    cls='vs-modal vs-unsaved-dialog'):
                with header(cls='vs-unsaved-header'):
                    with div(cls='vs-unsaved-icon'):
                        icon('warning')
                    with div():
                        h2(
                            translate('Close all tabs?'),
                            id='close-tabs-title')
                        p(
                            translate(
                                'Preferences require all open tabs to be '
                                'closed.'),
                            id='close-tabs-description', cls='vs-muted')
                with div(cls='vs-unsaved-explanation'):
                    p(translate(
                            'Any unsaved changes will be reviewed before '
                            'each tab is closed.'))
                with div(cls='vs-dialog-actions vs-unsaved-actions'):
                    button(
                        translate('Cancel'), type='button',
                        cls='vs-button', data_close_modal='true',
                        autofocus=True)
                    with button(
                            type='button',
                            cls='vs-button vs-button-primary',
                hx_post=Pool().get('cassini.preferences').url(),
                            hx_vals=json.dumps({'close_tabs': 'true'}),
                            hx_target='#workspace',
                            hx_swap='outerHTML'):
                        icon('close')
                        span(translate('Close tabs and continue'))
        return backdrop

    def render_preferences(self, engine):
        User = Pool().get('res.user')
        view = User.get_preferences_fields_view()
        if engine.interface.data.get('preferences_open'):
            state = engine.interface.component('preferences')
        else:
            state = engine.open_preferences(User.get_preferences(False))
        pages = state.setdefault('pages', {})
        values = decode_value(state.get('values', {}))
        values.setdefault('active', User(Transaction().user).active)
        pseudo_tab = {
            'id': 'preferences',
            'kind': 'preferences',
            'model': 'res.user',
            'pages': pages,
            'screen_width': engine.interface.data.get('screen_width'),
            }
        pseudo_record = {
            'key': str(Transaction().user),
            'id': Transaction().user,
            'values': values,
            'x2many': state.setdefault('x2many', {}),
            }
        renderer = WidgetRenderer(
            pseudo_tab, pseudo_record, view,
            editable=True, endpoint='preferences')
        root = parse_architecture(view)
        view_renderer = ViewRenderer(self.engine.interface)
        SavePreferences = Pool().get('cassini.save.preferences')
        ClosePreferences = Pool().get('cassini.close.preferences')
        with div(
                cls='vs-modal-backdrop',
                data_close_url=ClosePreferences.url()) as backdrop:
            with section(
                    role='dialog', aria_modal='true',
                    aria_labelledby='preferences-title',
                    cls='vs-modal vs-preferences-dialog'):
                h2(translate('Preferences'), id='preferences-title')
                with form(
                        id='preferences-form',
                        cls='vs-form',
                        method='post',
                        action=SavePreferences.url(),
                        style=view_renderer.form_grid_style(
                            root, root.attrib.get('col', 4))
                        ) as preferences_form:
                    view_renderer.form_children(
                        preferences_form,
                        root, renderer, pseudo_tab, pseudo_record)
                    with div(cls='vs-dialog-actions'):
                        button(
                            translate('Cancel'), type='button', cls='vs-button',
                            hx_post=ClosePreferences.url(),
                            hx_target='#modal',
                            hx_swap='innerHTML')
                        button(
                            translate('Save'), type='submit',
                            cls='vs-button vs-button-primary')
                div(
                    id='relation-modal',
                    cls='vs-nested-modal-host')
        return backdrop

    def continue_after_closing_tabs(self, engine):
        while engine.interface.tabs:
            tab = engine.interface.tabs[0]
            if has_unsaved_changes(tab):
                engine.interface.activate(tab['id'])
                engine.save()
                return unsaved_changes_response(
                    engine, tab, 'open-preferences')
            engine.close_tab(tab['id'])

        with div(id='modal', cls='vs-modal-host') as modal:
            modal.add(self.render_preferences(engine))
        return workspace_response(
            engine, {'HX-Push-Url': active_workspace_url(engine)},
            [Fragment('modal', modal)])

    def render(self):
        login = self.require_user()
        if login:
            return login
        engine = self.engine
        shell_state = engine.interface.component('shell', {})
        if shell_state.get('user_menu'):
            shell_state['user_menu'] = False
            engine.save()
        if not engine.interface.data.get('preferences_open'):
            request = current_request()
            close_tabs = bool(
                request and request.form.get('close_tabs') == 'true')
            if engine.interface.tabs and not close_tabs:
                return self.close_tabs_confirmation()
            if close_tabs:
                return self.continue_after_closing_tabs(engine)
        return self.render_preferences(engine)


class SwitchPreferencePage(SaoEndpoint):
    'Switch Cassini Preferences Notebook Page'
    __name__ = 'cassini.switch.preference.page'
    _url = (
        '/preferences/notebook/<string:notebook>/page/<int:page>')

    notebook = fields.Char('Notebook')
    page = fields.Integer('Page')

    @handle_endpoint_errors
    def render(self):
        if not self.engine.interface.data.get('preferences_open'):
            raise ValueError(translate('Preferences are not open'))
        path = self.notebook.removeprefix('n-').split('-')
        if (
                not self.notebook.startswith('n-')
                or not path
                or any(not item.isdigit() for item in path)
                or self.page < 0
                or self.page > 99):
            raise ValueError(translate('Unknown preferences page'))
        state = self.engine.interface.component('preferences')
        state.setdefault('pages', {})[self.notebook] = self.page
        self.engine.save()
        return Response('', status=204)


class SavePreferences(SaoEndpoint):
    'Save Cassini Preferences'
    __name__ = 'cassini.save.preferences'
    _url = '/preferences/save'

    @handle_endpoint_errors
    def render(self):
        User = Pool().get('res.user')
        view = User.get_preferences_fields_view()
        request = current_request()
        engine = self.engine
        state = engine.interface.component('preferences')
        draft = decode_value(state.get('values', {}))
        changed = set(state.get('changed', []))
        values = {
            name: draft[name]
            for name in view.get('fields', {})
            if name in draft and name in changed
            }
        for name, definition in view.get('fields', {}).items():
            if name not in changed:
                continue
            if name not in request.form:
                if definition.get('type') == 'boolean':
                    values[name] = False
                continue
            field = User._fields.get(name)
            raw_value = request.form.getlist(name)
            raw_value = (
                raw_value
                if definition.get('type') in {
                    'many2many', 'one2many', 'multiselection'}
                else raw_value[-1])
            if field:
                if definition.get('type') != field._type:
                    value = raw_value
                    if definition.get('type') == 'selection':
                        for key, title in definition.get('selection', []):
                            if str(key) == str(raw_value):
                                value = key
                                break
                    values[name] = value
                else:
                    values[name] = self.engine.parse_value(
                        field, raw_value, definition)
            else:
                values[name] = raw_value
        if values:
            User.set_preferences(values)
            from trytond.modules.voyager.voyager import CacheManager
            CacheManager.clear()
            if self.cache:
                self.cache.clear()
        engine.close_preferences()
        return redirect(
            '%s?_cassini_reload=%s' % (
                Pool().get('cassini.shell').url(), uuid.uuid4().hex),
            code=303)


class ClosePreferences(SaoEndpoint):
    'Close Cassini Preferences'
    __name__ = 'cassini.close.preferences'
    _url = '/preferences/close'

    @handle_endpoint_errors
    def render(self):
        self.engine.close_preferences()
        return Response('', content_type='text/html')


class PreferenceBinary(SaoEndpoint):
    'Cassini Preference Binary'
    __name__ = 'cassini.preference.binary'
    _url = '/preferences/binary/<string:field>'

    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        if not self.engine.interface.data.get('preferences_open'):
            return Response('', status=404)
        User = Pool().get('res.user')
        view = User.get_preferences_fields_view()
        field = User._fields.get(self.field)
        if (
                self.field not in view.get('fields', {})
                or not field
                or field._type != 'binary'):
            return Response('', status=404)
        state = self.engine.interface.component('preferences')
        values = decode_value(state.get('values', {}))
        content = values.get(self.field)
        if not isinstance(content, bytes):
            content = getattr(User(Transaction().user), self.field) or b''
        if not content:
            return Response('', status=404)
        if content.startswith(b'\x89PNG\r\n\x1a\n'):
            content_type = 'image/png'
        elif content.startswith(b'\xff\xd8\xff'):
            content_type = 'image/jpeg'
        elif content.startswith((b'GIF87a', b'GIF89a')):
            content_type = 'image/gif'
        else:
            content_type = 'application/octet-stream'
        response = Response(content, content_type=content_type)
        response.headers['Content-Disposition'] = 'inline'
        response.headers['Cache-Control'] = 'no-store'
        return response


class UpdatePreferenceField(SaoEndpoint):
    'Update Cassini Preference Field'
    __name__ = 'cassini.update.preference.field'
    _url = '/preferences/field/<string:field>'

    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        User = Pool().get('res.user')
        view = User.get_preferences_fields_view()
        definition = view.get('fields', {}).get(self.field, {})
        request = current_request()
        uploaded = request.files.get(self.field) if request else None
        if uploaded:
            raw_value = uploaded.read()
        else:
            raw_values = request.form.getlist(self.field)
            raw_value = (
                raw_values
                if definition.get('type') in {
                    'many2many', 'one2many', 'multiselection'}
                else (raw_values[-1] if raw_values else None))
        state, changed = self.engine.update_preference(
            view, self.field, raw_value)
        pseudo_tab = {
            'id': 'preferences',
            'kind': 'preferences',
            'model': 'res.user',
            'pages': state.get('pages', {}),
            'screen_width': self.engine.interface.data.get('screen_width'),
            }
        values = decode_value(state.get('values', {}))
        values.setdefault('active', User(Transaction().user).active)
        pseudo_record = {
            'key': str(Transaction().user),
            'id': Transaction().user,
            'values': values,
            'x2many': state.setdefault('x2many', {}),
            }
        renderer = WidgetRenderer(
            pseudo_tab, pseudo_record, view,
            editable=True, endpoint='preferences')
        visible_changed = [
            name for name in changed
            if name in view.get('fields', {})]
        attributes = field_attributes(view, self.field)
        widget = (
            attributes.get('widget')
            or view.get(
                'fields', {}).get(self.field, {}).get('type', 'char'))
        preserve_self = widget in (
            WidgetRenderer.text_widgets
            | WidgetRenderer.textarea_widgets
            | WidgetRenderer.date_widgets)
        if self.field in visible_changed:
            visible_changed.remove(self.field)
        if not preserve_self:
            visible_changed.insert(0, self.field)
        fragments = [
            Fragment(
                dom_id(
                    'field', 'preferences',
                    str(Transaction().user), name),
                renderer.render(
                    name, field_attributes(view, name)))
            for name in visible_changed
            ]
        return FragmentResponse.response(
            fragments, stream=len(fragments) > 1,
            all_out_of_band=True)


class UpdateWizardField(SaoEndpoint):
    'Update Cassini Wizard Field'
    __name__ = 'cassini.update.wizard.field'
    _url = '/tab/<string:tab>/wizard/field/<string:field>'

    tab = fields.Char('Tab')
    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        view = decode_value(tab.get('view', {}))
        definition = view.get('fields', {}).get(self.field, {})
        request = current_request()
        raw_values = request.form.getlist(self.field)
        raw_value = (
            raw_values
            if definition.get('type') in {
                'many2many', 'one2many', 'multiselection'}
            else (raw_values[-1] if raw_values else None))
        tab, changed = self.engine.update_wizard_field(
            self.tab, self.field, raw_value)
        view = decode_value(tab['view'])
        pseudo_tab = {
            'id': tab['id'],
            'model': view['model'],
            'kind': 'wizard',
            'pages': tab.get('pages', {}),
            }
        pseudo_record = {
            'key': 'wizard',
            'values': decode_value(tab.get('values', {})),
            }
        renderer = WidgetRenderer(
            pseudo_tab, pseudo_record, view,
            editable=True, endpoint='wizard')
        visible_changed = [
            name for name in changed
            if name in view.get('fields', {})]
        attributes = field_attributes(view, self.field)
        widget = (
            attributes.get('widget')
            or view.get(
                'fields', {}).get(self.field, {}).get('type', 'char'))
        preserve_self = widget in (
            WidgetRenderer.text_widgets
            | WidgetRenderer.textarea_widgets
            | WidgetRenderer.date_widgets)
        if self.field in visible_changed:
            visible_changed.remove(self.field)
        if not preserve_self:
            visible_changed.insert(0, self.field)
        fragments = [
            Fragment(
                dom_id('field', self.tab, 'wizard', name),
                renderer.render(
                    name, field_attributes(view, name)))
            for name in visible_changed
            ]
        return FragmentResponse.response(
            fragments, stream=len(fragments) > 1,
            all_out_of_band=True)


class WizardStep(SaoEndpoint):
    'Continue Cassini Wizard'
    __name__ = 'cassini.wizard.step'
    _url = '/tab/<string:tab>/wizard/<string:state>'

    tab = fields.Char('Tab')
    state = fields.Char('State')

    @handle_endpoint_errors
    def render(self):
        tab = self.engine.interface.get_tab(self.tab)
        view = tab and tab.get('view')
        if not view:
            raise ValueError(translate('Wizard has no current view'))
        view = decode_value(view)
        Model = Pool().get(view['model'])
        request = current_request()
        values = {}
        current_values = decode_value(tab.get('values', {}))
        for name, definition in view.get('fields', {}).items():
            field = Model._fields.get(name)
            if name in request.form:
                raw_values = request.form.getlist(name)
                raw_value = (
                    raw_values
                    if definition.get('type') in {
                        'many2many', 'one2many', 'multiselection'}
                    else raw_values[-1])
                values[name] = (
                    self.engine.parse_value(field, raw_value, definition)
                    if field else raw_value)
            elif definition.get('type') == 'boolean':
                values[name] = False
            elif name in current_values:
                values[name] = current_values[name]
        engine = self.engine
        _, downloads = engine.wizard_step(
            self.tab, self.state, values)
        headers = {
            'HX-Push-Url': active_workspace_url(engine),
            }
        if downloads:
            ReportDownload = Pool().get(
                'cassini.report.download')
            headers['HX-Trigger'] = json.dumps({
                        'voyager-download': {
                            'urls': [
                                ReportDownload.url(key=key)
                                for key in downloads
                                ],
                            },
                        })
        return workspace_response(engine, headers)


class ReportDownload(SaoEndpoint):
    'Download Cassini Report'
    __name__ = 'cassini.report.download'
    _url = '/report/<string:key>'

    key = fields.Char('Key')

    @handle_endpoint_errors
    def render(self):
        return self.engine.download_report(self.key)


class DownloadBinary(SaoEndpoint):
    'Download Cassini Binary'
    __name__ = 'cassini.download.binary'
    _url = (
        '/tab/<string:tab>/record/<string:record>/binary/<string:field>')

    tab = fields.Char('Tab')
    record = fields.Char('Record')
    field = fields.Char('Field')

    @handle_endpoint_errors
    def render(self):
        return self.engine.binary_response(
            self.tab, self.record, self.field)


class StateComponent(SaoEndpoint):
    """Render a registered custom component from its persistent state."""
    'Cassini State Component'
    __name__ = 'cassini.state.component'
    _url = '/component/<string:component>'

    component = fields.Char('Component')

    def render(self):
        login = self.require_user()
        if login:
            return login
        state = self.engine.interface.component(self.component)
        content = render_state_component(
            self.component, state, {
                'session': self.session,
                'user': self.session.system_user,
                'site': self.site,
                })
        with div(
                id=dom_id('component', self.component),
                cls='vs-state-component',
                data_component=self.component) as wrapper:
            wrapper.add(content)
        return wrapper


class UpdateStateComponent(SaoEndpoint):
    """Merge JSON state and return only the affected custom component."""
    'Update Cassini State Component'
    __name__ = 'cassini.update.state.component'
    _url = '/component/<string:component>/state'

    component = fields.Char('Component')
    payload = fields.Text('Payload')

    @handle_endpoint_errors
    def render(self):
        login = self.require_user()
        if login:
            return login
        try:
            values = json.loads(self.payload or '{}')
        except json.JSONDecodeError as exception:
            raise ValueError(translate('Component state must be valid JSON')) from exception
        if not isinstance(values, dict):
            raise ValueError(translate('Component state must be a JSON object'))
        engine = self.engine
        engine.interface.component(self.component).update(values)
        engine.save()
        state = engine.interface.component(self.component)
        content = render_state_component(
            self.component, state, {
                'session': self.session,
                'user': self.session.system_user,
                'site': self.site,
                })
        with div(
                id=dom_id('component', self.component),
                cls='vs-state-component',
                data_component=self.component) as wrapper:
            wrapper.add(content)
        return wrapper

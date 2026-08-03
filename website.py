from datetime import datetime, timedelta
from hashlib import sha256

from trytond.modules.voyager.voyager import (
    CACHE_ENABLED, CACHE_TIMEOUT, VoyagerCache)
from trytond.pool import Pool, PoolMeta
from trytond.protocols.wrappers import remove_auth_cookies
from trytond.transaction import Transaction
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

_CACHE = (
    VoyagerCache('cassini.cache', duration=CACHE_TIMEOUT)
    if CACHE_ENABLED else None)


def cassini_session_id(database, token):
    """Return an opaque Voyager session key for a Tryton session token."""
    value = '%s\0%s' % (database, token)
    return 'cassini-' + sha256(value.encode()).hexdigest()


def cassini_user_id(request):
    """Validate Cassini authentication with Tryton's session storage."""
    cache_key = 'cassini.authenticated_user'
    if cache_key in request.environ:
        return request.environ[cache_key] or None
    authentication = request.session
    user_id = None
    if (authentication
            and Pool().get('ir.session').check(
                authentication.userid, authentication.token)):
        user_id = authentication.userid
    request.environ[cache_key] = user_id or False
    return user_id


class Session(metaclass=PoolMeta):
    __name__ = 'www.session'

    @classmethod
    def get(cls, request):
        site_id = Transaction().context.get('site')
        site = Pool().get('www.site')(site_id) if site_id else None
        if not site or site.type != 'cassini':
            return super().get(request)

        authentication = request.session
        user_id = cassini_user_id(request)
        if not user_id:
            session = super().get(request)
            # A legacy Voyager cookie must never keep Cassini authenticated
            # after the corresponding Tryton session has expired.
            if session.system_user:
                session.set_system_user(None)
            return session

        prepared_session = request.environ.get('cassini.www_session')
        if prepared_session:
            return prepared_session

        session_id = cassini_session_id(
            Transaction().database.name, authentication.token)
        sessions = cls.search([
                ('site', '=', site.id),
                ('session_id', '=', session_id),
                ], limit=1)
        if sessions:
            session, = sessions
            if (not session.system_user
                    or session.system_user.id != user_id):
                session.system_user = user_id
                session.save()
        else:
            session = cls()
            session.site = site
            session.session_id = session_id
            session.system_user = user_id
            session.expiration_date = datetime.now() + timedelta(
                seconds=site.session_lifetime)
            session.save()
        return session


class Site(metaclass=PoolMeta):
    __name__ = 'www.site'
    _cassini_routes = {}

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.type.selection.append(('cassini', 'Cassini'))

    def get_cache(self, session, request):
        if self.type == 'cassini':
            # Cache invalidations are propagated asynchronously between
            # workers.  The first request after saving preferences must read
            # the new user context from the database instead of risking a
            # stale language, company or warehouse from another worker.
            if getattr(request, 'args', {}).get('_cassini_reload'):
                return None
            return _CACHE
        return super().get_cache(session, request)

    @classmethod
    def dispatch(cls, site_type, site_id, request, user_id=None,
            web_prefix=None):
        if site_type == 'cassini':
            prefix = (web_prefix or '').rstrip('/')
            authenticated_user = cassini_user_id(request)
            public_paths = {
                prefix,
                prefix + '/',
                prefix + '/login',
                prefix + '/login-request',
                }
            public = (
                request.path in public_paths
                or request.path.startswith(prefix + '/asset/'))
            if not public and not authenticated_user:
                login_url = prefix + '/login'
                if request.headers.get('HX-Request'):
                    response = Response(
                        '', headers={'HX-Redirect': login_url})
                else:
                    response = redirect(login_url)
                remove_auth_cookies(
                    response, Transaction().database.name)
                response.delete_cookie('session_id', path='/')
                return response
            if authenticated_user:
                if site_id:
                    site = cls(site_id)
                else:
                    sites = cls.search([
                            ('type', '=', 'cassini'),
                            ], limit=1)
                    if sites:
                        site, = sites
                    else:
                        site = cls()
                        site.name = 'cassini'
                        site.type = 'cassini'
                        site.url = request.url_root
                        site.save()
                authentication = request.session
                session_id = cassini_session_id(
                    Transaction().database.name, authentication.token)
                Session = Pool().get('www.session')
                sessions = Session.search([
                        ('site', '=', site.id),
                        ('session_id', '=', session_id),
                        ], limit=1)
                session = sessions[0] if sessions else None
                ready = (
                    session
                    and session.system_user
                    and session.system_user.id == authenticated_user)
                if not ready:
                    if not session:
                        session = Session()
                        session.site = site
                        session.session_id = session_id
                        session.expiration_date = (
                            datetime.now() + timedelta(
                                seconds=site.session_lifetime))
                    session.system_user = authenticated_user
                    session.save()
                    Pool().get('cassini.workspace').get(
                        session,
                        Pool().get('res.user')(authenticated_user))
                    shell_url = prefix + '/app'
                    if request.headers.get('HX-Request'):
                        response = Response(
                            '', headers={'HX-Redirect': shell_url})
                    else:
                        response = redirect(shell_url)
                    response.delete_cookie('session_id', path='/')
                    return response
                request.environ['cassini.www_session'] = session
        response = super().dispatch(
            site_type, site_id, request, user_id, web_prefix)
        if site_type == 'cassini' and response:
            # Cassini authenticates with Tryton's standard persistent cookie.
            # Remove Voyager's independent browser-session cookie so it can
            # neither shadow nor outlive the authenticated Tryton session.
            response.delete_cookie('session_id', path='/')
        return response

    def get_site_info(self, web_prefix):
        if self.type != 'cassini':
            return super().get_site_info(web_prefix)
        key = (
            Transaction().database.name,
            self.url,
            web_prefix,
            )
        cached = self._cassini_routes.get(key)
        if cached is None:
            web_map, _adapter, endpoint_args, error_handlers = (
                super().get_site_info(web_prefix))
            cached = (web_map, endpoint_args, error_handlers)
            self._cassini_routes[key] = cached
        web_map, endpoint_args, error_handlers = cached
        return (
            web_map,
            web_map.bind(self.url, '/'),
            endpoint_args,
            error_handlers)

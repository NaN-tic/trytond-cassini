from trytond.modules.voyager.voyager import (
    CACHE_ENABLED, CACHE_TIMEOUT, VoyagerCache)
from trytond.pool import PoolMeta
from trytond.transaction import Transaction

from .i18n import lazy_translate

_CACHE = (
    VoyagerCache('cassini.cache', duration=CACHE_TIMEOUT)
    if CACHE_ENABLED else None)


class Site(metaclass=PoolMeta):
    __name__ = 'www.site'
    _cassini_routes = {}

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.type.selection.append(('cassini', lazy_translate('Cassini')))

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

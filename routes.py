import os
from time import perf_counter

from trytond.protocols.wrappers import (
    allow_null_origin, with_pool, with_transaction)
from trytond.transaction import Transaction
from trytond.wsgi import SharedDataMiddlewareIndex, app

MODULE_PATH = os.path.dirname(os.path.realpath(__file__))
STATIC_PATH = os.path.join(MODULE_PATH, 'static')
SAO_ICON_PATH = os.path.abspath(os.path.join(
        MODULE_PATH, '..', '..', '..', '..', 'sao', 'images'))
HELP_ICON_PATH = os.path.abspath(os.path.join(
        MODULE_PATH, '..', '..', '..', '..', '..', 'roots',
        'private', 'sao', 'help_popup', 'img'))
PRIVATE_SAO_IMAGE_PATH = os.path.abspath(os.path.join(
        MODULE_PATH, '..', '..', '..', '..', '..', 'roots',
        'private', 'sao', 'images'))
app.wsgi_app = SharedDataMiddlewareIndex(app.wsgi_app, {
        '/cassini-static': STATIC_PATH,
        '/cassini-icons': SAO_ICON_PATH,
        '/cassini-help-icons': HELP_ICON_PATH,
        '/cassini-private-images': PRIVATE_SAO_IMAGE_PATH,
        })


@app.route(
    '/<database_name>/cassini/',
    defaults={'path': None}, methods=['GET', 'POST'])
@app.route(
    '/<database_name>/cassini/<path:path>',
    methods=['GET', 'POST'])
@allow_null_origin
@with_pool
@with_transaction(readonly=False)
def web(request, pool, path):
    Site = pool.get('www.site')
    started = perf_counter()
    response = Site.dispatch(
        'cassini', None, request, 1,
        f'/{Transaction().database.name}/cassini')
    duration = (perf_counter() - started) * 1000
    response.headers['Server-Timing'] = (
        'cassini;dur=%.3f' % duration)
    response.headers['X-Cassini-Ms'] = '%.3f' % duration
    response.headers['Cache-Control'] = (
        'no-store, no-cache, must-revalidate, private, max-age=0')
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

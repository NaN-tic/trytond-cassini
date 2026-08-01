import base64
import os

from dominate.tags import img
from dominate.util import raw

from trytond.pool import Pool


ICON_ROOT = '/cassini-icons/tryton-'
SAO_ICON_PATH = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', '..', '..', 'sao', 'images'))
CUSTOM_ICONS = {
    'goblin': '/cassini-help-icons/goblin.svg',
    }


def icon(name, label=None, cls='vs-icon'):
    """Return the same SVG icon asset used by Sao."""
    source = CUSTOM_ICONS.get(name)
    icon_name = 'tryton-' + name
    if source is None:
        source = ICON_ROOT + name + '.svg'
        if not os.path.isfile(os.path.join(SAO_ICON_PATH, icon_name + '.svg')):
            Icon = Pool().get('ir.ui.icon')
            icons = Icon.search([('name', '=', icon_name)], limit=1)
            if icons:
                data = base64.b64encode(
                    icons[0].icon.encode('utf-8')).decode('ascii')
                source = 'data:image/svg+xml;base64,' + data
    return img(
        src=source,
        alt=label or '',
        aria_hidden='false' if label else 'true',
        cls=cls)


def fullscreen_icon(cls='vs-icon'):
    """Return the exact full-screen glyph used by the private Sao shell."""
    return raw(
        '<svg class="%s" viewBox="0 -960 960 960" '
        'aria-hidden="true" focusable="false" fill="currentColor">'
        '<path d="m 300.13115,-379.86885 1.6105,-202.67804 '
        'L 200,-480 Z m 359.33508,0.40262 L 760,-480 '
        '659.86885,-579.32591 Z M 160,-160 c -22,0 '
        '-40.83333,-7.83333 -56.5,-23.5 C 87.833333,'
        '-199.16667 80,-218 80,-240 v -480 c 0,-22 '
        '7.833333,-40.83333 23.5,-56.5 15.66667,'
        '-15.66667 34.5,-23.5 56.5,-23.5 h 640 c 22,0 '
        '40.83333,7.83333 56.5,23.5 15.66667,15.66667 '
        '23.5,34.5 23.5,56.5 v 480 c 0,22 -7.83333,'
        '40.83333 -23.5,56.5 C 840.83333,-167.83333 '
        '822,-160 800,-160 z m 0,-80 H 800 V -720 H '
        '160 Z m 0,0 v -480 z"/></svg>' % cls)


def filter_icon(cls='vs-icon'):
    """Return the funnel glyph used for Sao's advanced filter."""
    return raw(
        '<svg class="%s" viewBox="0 -960 960 960" '
        'aria-hidden="true" focusable="false" fill="currentColor">'
        '<path d="M440-160q-17 0-28.5-11.5T400-200v-240L168-730'
        'q-15-20-4.5-45t36.5-25h560q26 0 36.5 25t-4.5 45L560-440'
        'v240q0 17-11.5 28.5T520-160h-80Zm40-308 197-252H283'
        'l197 252v188-188Z"/></svg>' % cls)


def theme_icon(dark=False, cls='vs-icon'):
    """Render an unambiguous sun/moon icon for the current theme."""
    path = (
        'M480-120q-150 0-255-105T120-480q0-150 105-255t255-105'
        'q14 0 27.5 1t26.5 3q-41 29-65 75t-24 101q0 90 62.5 '
        '152.5T660-445q55 0 101-24t75-65q2 13 3 26.5t1 27.5'
        'q0 150-105 255T480-120Z'
        if dark else
        'M440-760v-160h80v160h-80Zm266 110-55-55 112-117 56 '
        '59-113 113Zm54 210v-80h160v80H760ZM440-40v-160h80v160'
        'h-80ZM254-650 141-763l56-56 113 113-56 56Zm508 509'
        'L650-254l56-56 113 113-57 56ZM40-440v-80h160v80H40Zm157 '
        '299-56-56 113-113 56 56L197-141Zm283-99q-100 0-170-70'
        't-70-170q0-100 70-170t170-70q100 0 170 70t70 170q0 '
        '100-70 170t-170 70Z')
    return raw(
        '<svg class="%s" viewBox="0 -960 960 960" '
        'aria-hidden="true" focusable="false" fill="currentColor">'
        '<path d="%s"/></svg>' % (cls, path))

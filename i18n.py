import hashlib
import re

from trytond.pool import Pool
from trytond.tools.string_ import LazyString
from trytond.transaction import Transaction


JAVASCRIPT_SOURCES = (
    'Action',
    'A maximum of five attachments is allowed.',
    'Attachment',
    'Cancel',
    'Close',
    'Close Tab',
    'Confirm action',
    'Continue',
    'Could not save the column widths.',
    'Delete',
    'Direct printing failed: %(error)s',
    'Duplicate',
    'Global search',
    'Global shortcuts',
    'Keyboard shortcuts',
    'New',
    'Next',
    'Next tab',
    'Note',
    'OK',
    'Previous',
    'Previous tab',
    'Print',
    'Plotly could not be initialized.',
    'QZ Tray could not be initialized.',
    'Relate',
    'Reload/Undo',
    'Remote assistance could not be initialized.',
    'Remote assistance did not load.',
    'Remove %(file)s',
    'Save',
    'Screen capture is not available.',
    'Screen recording is not available.',
    'Search',
    'Show this help',
    'Show/Hide access keys',
    'Speech recognition is not available.',
    'Start a support session by sharing the current browser tab.',
    'Support',
    'Switch',
    'Tab shortcuts',
    'The assistant voice is not available.',
    'The audio could not be transcribed.',
    'The chart data is not valid.',
    'The microphone could not be started.',
    'The recording could not be started.',
    'The screenshot could not be captured.',
    'The server could not complete this action.',
    'The requested JavaScript library could not be loaded.',
    )


def message_id(source):
    """Return the stable ``ir.message`` identifier for a source string."""
    slug = re.sub(r'[^a-z0-9]+', '_', source.lower()).strip('_')
    slug = slug[:48] or 'text'
    digest = hashlib.sha1(source.encode('utf-8')).hexdigest()[:8]
    return 'msg_%s_%s' % (slug, digest)


def translate(source, **variables):
    """Translate a Cassini interface string in the request language."""
    transaction = Transaction()
    language = transaction.language if transaction.database else 'en'
    fuzzy = bool(
        transaction.context.get('fuzzy_translation', False)
        if transaction.context else False)
    key = (language, fuzzy)
    caches = getattr(transaction, '_cassini_translations', None)
    if caches is None:
        caches = transaction._cassini_translations = {}
    translations = caches.get(key)
    if translations is None:
        translations = {}
        pool = Pool()
        if transaction.database and pool.ready and language != 'en':
            Translation = pool.get('ir.translation')
            current_language = language
            while current_language:
                domain = [
                    ('module', '=', 'cassini'),
                    ('lang', '=', current_language),
                    ('type', '=', 'model'),
                    ('name', '=', 'ir.message,text'),
                    ('value', 'not in', ['', None]),
                    ]
                if not fuzzy:
                    domain.append(('fuzzy', '=', False))
                for translation in Translation.search(domain):
                    translations.setdefault(
                        translation.src, translation.value)
                current_language = (
                    current_language.rsplit('_', 1)[0]
                    if '_' in current_language else None)
        caches[key] = translations
    value = translations.get(source, source)
    if variables:
        value %= variables
    return value


def lazy_translate(source):
    """Translate model metadata when it is converted to text."""
    return LazyString(translate, source)


def javascript_translations():
    """Return strings needed by the static client-side behaviour."""
    return {
        source: translate(source)
        for source in JAVASCRIPT_SOURCES
        }

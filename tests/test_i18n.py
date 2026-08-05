import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree

import polib

from trytond.modules.cassini.i18n import javascript_translations
from trytond.modules.cassini.state import WORKSPACE_SESSION_UNIQUE
from trytond.modules.xgettext import _
from trytond.pool import Pool
from trytond.tests import test_tryton
from trytond.transaction import Transaction


MODULE_ROOT = Path(__file__).resolve().parent.parent


class TranslationTestCase(unittest.TestCase):

    def messages(self):
        root = ElementTree.parse(MODULE_ROOT / 'message.xml').getroot()
        return {
            record.attrib['id']: record.findtext('field')
            for record in root.findall('.//record')
            if record.attrib.get('model') == 'ir.message'
            }

    def xgettext_sources(self):
        sources = set()
        for path in MODULE_ROOT.glob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == '_'
                        and node.args):
                    continue
                self.assertEqual(len(node.args), 1)
                self.assertFalse(node.keywords)
                self.assertIsInstance(node.args[0], ast.Constant)
                self.assertIsInstance(node.args[0].value, str)
                sources.add(node.args[0].value)
        return sources

    def test_only_constraint_message_is_registered(self):
        self.assertEqual(self.messages(), {
                WORKSPACE_SESSION_UNIQUE.removeprefix('cassini.'):
                    'A Cassini session can only have one workspace.',
                })

    def test_all_messages_are_translated(self):
        messages = self.messages()
        xgettext_sources = self.xgettext_sources()
        for language in ('ca', 'es'):
            catalog = polib.pofile(
                str(MODULE_ROOT / 'locale' / (language + '.po')))
            translations = {
                (entry.msgctxt, entry.msgid)
                for entry in catalog
                if entry.msgctxt and entry.msgstr
                }
            for identifier, source in messages.items():
                context = 'model:ir.message,text:' + identifier
                self.assertIn((context, source), translations)
            for source in xgettext_sources:
                self.assertIn(('xgettext:x:', source), translations)


class RuntimeTranslationTestCase(unittest.TestCase):
    'Test Cassini runtime translations'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        test_tryton.activate_module('cassini')

    @test_tryton.with_transaction()
    def test_catalan_and_spanish(self):
        Translation = Pool().get('ir.translation')
        for language, expected in (
                ('ca', 'Cerca'),
                ('es', 'Buscar')):
            Translation.translation_import(
                language, 'cassini',
                str(MODULE_ROOT / 'locale' / (language + '.po')))
            with Transaction().set_context(language=language):
                self.assertEqual(
                    javascript_translations()['Search'], expected)
                self.assertEqual(_('Search'), expected)
                self.assertEqual(
                    _('Contextual documentation'),
                    'Documentació contextual'
                    if language == 'ca' else 'Documentación contextual')


if __name__ == '__main__':
    unittest.main()

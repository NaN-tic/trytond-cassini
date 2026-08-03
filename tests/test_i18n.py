import ast
import unittest
from pathlib import Path
from xml.etree import ElementTree

import polib

from trytond.modules.cassini.i18n import (
    JAVASCRIPT_SOURCES, message_id, translate)
from trytond.modules.cassini.engine import COMMON_SEARCH_FIELDS
from trytond.modules.cassini.state import WORKSPACE_SESSION_UNIQUE
from trytond.modules.xgettext import _
from trytond.pool import Pool
from trytond.tests import test_tryton
from trytond.transaction import Transaction


MODULE_ROOT = Path(__file__).resolve().parent.parent


class TranslationTestCase(unittest.TestCase):

    def interface_sources(self):
        sources = set(JAVASCRIPT_SOURCES)
        sources.add(WORKSPACE_SESSION_UNIQUE)
        sources.update(title for _name, title, _type in COMMON_SEARCH_FIELDS)
        for path in MODULE_ROOT.glob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in {
                            'translate', 'lazy_translate', 'message_id'}
                        and node.args):
                    continue
                for constant in ast.walk(node.args[0]):
                    if (
                            isinstance(constant, ast.Constant)
                            and isinstance(constant.value, str)):
                        sources.add(constant.value)
        return sources

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
                self.assertIsInstance(node.args[0], ast.Constant)
                self.assertIsInstance(node.args[0].value, str)
                sources.add(node.args[0].value)
        return sources

    def test_all_interface_sources_are_messages(self):
        messages = self.messages()
        expected = {
            message_id(source): source
            for source in self.interface_sources()
            }
        self.assertEqual(messages, expected)

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
                self.assertEqual(translate('Search'), expected)
                self.assertEqual(
                    _('Contextual documentation'),
                    'Documentació contextual'
                    if language == 'ca' else 'Documentación contextual')


if __name__ == '__main__':
    unittest.main()

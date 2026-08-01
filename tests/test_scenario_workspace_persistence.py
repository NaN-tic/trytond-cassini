import unittest
from datetime import datetime
from decimal import Decimal

from trytond.pool import Pool
from trytond.tests.test_tryton import DB_NAME, activate_module, drop_db
from trytond.transaction import Transaction


class TestWorkspacePersistence(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_module('cassini')

        with Transaction().start(DB_NAME, 1) as transaction:
            pool = Pool()
            Site = pool.get('www.site')
            Session = pool.get('www.session')
            User = pool.get('res.user')
            Workspace = pool.get('cassini.workspace')

            site, = Site.create([{
                        'name': 'Cassini Test',
                        'type': 'cassini',
                        'url': 'http://localhost/',
                        }])
            with Transaction().set_context(site=site.id):
                session = Session.new()
            workspace = Workspace.get(session, User(1))
            interface = workspace.interface()
            tab = interface.add_tab({
                    'title': 'Unsaved party',
                    'kind': 'window',
                    'model': 'res.user',
                    'records': {
                        'new-test': {
                            'key': 'new-test',
                            'id': None,
                            'values': {
                                'name': 'Still unsaved',
                                'amount': Decimal('12.30'),
                                'when': datetime(2030, 4, 5, 10, 30),
                                },
                            'dirty': ['name'],
                            'new': True,
                            },
                        },
                    'record_order': ['new-test'],
                    'current_record': 'new-test',
                    })
            interface.component('custom-counter', {'value': 0})['value'] = 7
            workspace.store(interface)
            workspace_id = workspace.id
            tab_id = tab['id']
            transaction.commit()

        with Transaction().start(DB_NAME, 1):
            Workspace = Pool().get('cassini.workspace')
            restored = Workspace(workspace_id).interface()
            restored_tab = restored.get_tab(tab_id)

            self.assertEqual(restored.data['active_tab'], tab_id)
            self.assertEqual(len(restored.tabs), 1)
            self.assertEqual(
                restored_tab['records']['new-test']['values']['name'],
                'Still unsaved')
            self.assertEqual(
                restored_tab['records']['new-test']['values']['amount'],
                Decimal('12.30'))
            self.assertEqual(
                restored_tab['records']['new-test']['values']['when'],
                datetime(2030, 4, 5, 10, 30))
            self.assertEqual(
                restored.component('custom-counter')['value'], 7)

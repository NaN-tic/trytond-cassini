from playwright.sync_api import Page, expect
from trytond.modules.company.tests import create_company
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestStockReferenceRelation(WebTestCase):
    modules = ['cassini', 'stock']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Location = pool.get('stock.location')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Party = pool.get('party.party')
            Shipment = pool.get('stock.shipment.in')
            Site = pool.get('www.site')
            User = pool.get('res.user')

            company = create_company('Cassini Stock Company')
            storage, = Location.create([{
                        'name': 'Cassini Storage',
                        'type': 'storage',
                        }])
            warehouse, = Location.create([{
                        'name': 'Cassini Warehouse',
                        'type': 'warehouse',
                        'input_location': storage.id,
                        'output_location': storage.id,
                        'storage_location': storage.id,
                        }])
            supplier, = Party.create([{
                        'name': 'Cassini Supplier',
                        }])
            Shipment.create([{
                        'company': company.id,
                        'supplier': supplier.id,
                        'warehouse': warehouse.id,
                        'warehouse_input': storage.id,
                        'warehouse_storage': storage.id,
                        }])
            User.write([User(1)], {
                    'companies': [('add', [company.id])],
                    'company': company.id,
                    })
            action = ActionWindow(ModelData.get_id(
                    'stock', 'act_shipment_in_form'))
            Menu.create([{
                        'name': 'Cassini Supplier Shipments',
                        'action': str(action),
                        }])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @browser()
    def test(self, page: Page):
        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        search = page.get_by_label('Global search')
        search.fill('Cassini Supplier Shipments')
        page.locator(
            '[data-global-search-result]',
            has_text='Cassini Supplier Shipments').click()
        shipment = page.locator('.vs-row').first
        shipment.dblclick()
        expect(page.locator(
            '[data-field="supplier"] [data-relation-input]')).to_have_value(
                'Cassini Supplier')
        page.locator(
            '.vs-local-tab-title', has_text='Incoming Moves').click()
        incoming_moves = page.locator('[data-field="incoming_moves"]')
        with page.expect_response(
                lambda response:
                '/field/incoming_moves/new' in response.url) as response:
            incoming_moves.get_by_role(
                'button', name='New', exact=True).click()
        self.assertLess(response.value.status, 400)
        move = page.locator('.vs-relation-record-dialog')
        expect(move).to_be_visible()
        expect(move.locator('.vs-form')).to_be_visible()
        expect(move.locator('[data-field="shipment"]')).to_have_count(0)

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestOnChange(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Site = pool.get('www.site')

            action, = ActionWindow.create([{
                        'name': 'Cassini Sequences',
                        'res_model': 'ir.sequence',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            for sequence, xml_id in enumerate(
                    ('sequence_view_tree', 'sequence_view_form'), 1):
                ActionWindowView.create([{
                            'sequence': sequence,
                            'view': ModelData.get_id('ir', xml_id),
                            'act_window': action.id,
                            }])
            Menu.create([{
                        'name': 'Cassini Sequences',
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
        page.locator('[data-panel-option="menu"]').click()
        page.get_by_role(
            'button', name='Cassini Sequences', exact=True).click()
        page.get_by_role('button', name='New', exact=True).click()

        expect(page.locator(
                '[data-field="number_increment"] input')).to_have_value('1')
        expect(page.locator(
                '[data-field="padding"] input')).to_have_value('0')
        prefix = page.locator('[data-field="prefix"] input')
        with page.expect_response(
                lambda response: '/field/prefix' in response.url):
            prefix.press_sequentially('INV-')
        expect(page.locator(
                '[data-field="preview"] input')).to_have_value('INV-1')

        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="prefix"] input')).to_have_value('INV-')
        expect(page.locator(
                '[data-field="preview"] input')).to_have_value('INV-1')

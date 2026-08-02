from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestImmediateSave(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            action, = ActionWindow.create([{
                        'name': 'Cassini Immediate Save',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Cassini Immediate Save',
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
            'button', name='Cassini Immediate Save', exact=True).click()

        page.get_by_role('button', name='New').click()
        name = page.locator('[data-field="name"] input')
        expect(name).to_be_focused()
        name.fill('Saved Without Waiting')
        page.get_by_role('button', name='Save', exact=True).click()

        expect(page.locator('[data-field="name"] input')).to_have_value(
            'Saved Without Waiting')
        expect(page.locator('.vs-window-dirty-status')).to_have_count(0)
        with Transaction().start(self.database, 1):
            Group = Pool().get('res.group')
            self.assertEqual(Group.search([
                        ('name', '=', 'Saved Without Waiting'),
                        ], count=True), 1)

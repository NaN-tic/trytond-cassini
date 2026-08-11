from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestFormSwitchLoading(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            first, second = Group.create([
                    {'name': 'Cassini Form Loading A'},
                    {'name': 'Cassini Form Loading B'},
                    ])
            action, = ActionWindow.create([{
                        'name': 'Cassini Form Loading',
                        'res_model': 'res.group',
                        'domain': '[["id", "in", [%d, %d]]]' % (
                            first.id, second.id),
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Cassini Form Loading',
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
            'button', name='Cassini Form Loading', exact=True).click()

        page.get_by_label('Switch view').click()
        expect(page.get_by_text(
            'Cassini Form Loading A', exact=True)).to_be_visible()
        name = page.locator('[data-field="name"] input')
        name.focus()
        with page.expect_response(
                lambda response: response.url.endswith('/record/next')):
            name.press('Control+ArrowDown')
        expect(page.locator('[data-field="name"] input')).to_have_value(
            'Cassini Form Loading B')

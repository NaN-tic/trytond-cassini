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
            Export = pool.get('ir.export')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            first, second = Group.create([
                    {'name': 'Cassini Form Loading A'},
                    {'name': 'Cassini Form Loading B'},
                    ])
            Export.set({
                    'name': 'Cassini Toolbar Export',
                    'resource': 'res.group',
                    'export_fields': [{'name': 'name'}],
                    })
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

        with page.expect_response(
                lambda response: '/select?row=true' in response.url) \
                as response_info:
            page.get_by_text('Cassini Form Loading A', exact=True).click()
        response_markup = response_info.value.text()
        self.assertNotIn('vs-search-toolbar', response_markup)
        self.assertIn(
            'hx-swap-oob="outerHTML:#toolbar-actions-state-',
            response_markup)
        print_menu = page.locator(
            'details.vs-action-popup[data-action-category="print"]')
        print_menu.locator('summary').click()
        expect(print_menu.get_by_role(
                'menuitem', name='Cassini Toolbar Export')).to_be_visible()
        window_menu = page.locator('details.vs-window-menu')
        window_menu.locator('.vs-window-title').click()
        expect(window_menu.get_by_role(
                'menuitem', name='Cassini Toolbar Export')).to_have_count(0)
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

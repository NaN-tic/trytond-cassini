from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestReport(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            Site = Pool().get('www.site')
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
            'button', name='Expand Administration').click()
        page.get_by_role('button', name='Expand Models').click()
        page.locator(
            'button.vs-menu-action:text-is("Models")').click()

        expect(page.locator('.vs-screen')).to_be_visible()
        print_menu = page.locator(
            'details.vs-action-popup', has_text='Graph')
        print_menu.locator('summary').click()
        expect(print_menu).to_have_attribute('open', '')
        page.locator('.vs-active-panel').click(
            position={'x': 2, 'y': 2})
        expect(print_menu).not_to_have_attribute('open', '')
        print_menu.locator('summary').click()
        print_menu.get_by_role(
            'menuitem', name='Graph', exact=True).click()
        expect(print_menu).not_to_have_attribute('open', '')
        expect(page.get_by_role(
            'dialog', name='Graph')).to_be_visible()
        expect(page.locator('.vs-wizard')).to_be_visible()
        expect(page.locator(
                '[data-field="level"] input')).to_have_value('1')

        with page.expect_download(timeout=30000) as download_info:
            page.get_by_role('button', name='Print', exact=True).click()
        download = download_info.value
        self.assertEqual(download.suggested_filename, 'Graph.png')
        expect(page.locator('.vs-wizard')).not_to_be_visible()

        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-wizard')).not_to_be_visible()
        print_menu = page.locator(
            'details.vs-action-popup', has_text='Graph')
        print_menu.locator('summary').click()
        expect(print_menu.get_by_role(
                'menuitem', name='Graph', exact=True)).to_be_visible()

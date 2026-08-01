import re

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestMultipleTabs(WebTestCase):
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
                        'name': 'Persistent Tabs',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Persistent Tabs',
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

        menu = page.get_by_role(
            'button', name='Persistent Tabs', exact=True)
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            menu.click()
        expect(page.locator('.vs-tab')).to_have_count(1)
        page.get_by_role('button', name='New', exact=True).click()
        first_name = page.locator('[data-field="name"] input')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            first_name.press_sequentially('First unsaved tab')

        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            menu.click()
        expect(page.locator('.vs-tab')).to_have_count(2)
        page.get_by_role('button', name='New', exact=True).click()
        second_name = page.locator('[data-field="name"] input')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            second_name.press_sequentially('Second unsaved tab')

        expect(page.locator('.vs-tab')).to_have_count(2)
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    'Second unsaved tab')

        first_tab = page.locator('.vs-tab-title').nth(0)
        first_url = first_tab.get_attribute('hx-post')
        with page.expect_response(
                lambda response: response.url.endswith(first_url)):
            first_tab.click()
        expect(page).to_have_url(
            re.compile('%s$' % re.escape(first_url)))
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    'First unsaved tab')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-tab')).to_have_count(2)
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    'First unsaved tab')

        page.locator('.vs-tab-close').nth(1).click()
        dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text(
                'Second unsaved tab', exact=True)).to_be_visible()
        dialog.get_by_role(
            'button', name='Close without saving').click()
        expect(page.locator('.vs-tab')).to_have_count(1)

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestWizard(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWizard = pool.get('ir.action.wizard')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            dialog_action, window_action = ActionWizard.create([
                    {
                        'name': 'Cassini URI Wizard',
                        'wiz_name': 'www.uri.builder',
                        },
                    {
                        'name': 'Cassini URI Wizard Window',
                        'wiz_name': 'www.uri.builder',
                        'window': True,
                        },
                    ])
            Menu.create([
                    {
                        'name': 'Cassini URI Wizard',
                        'action': str(dialog_action),
                        },
                    {
                        'name': 'Cassini URI Wizard Window',
                        'action': str(window_action),
                        },
                    ])
            sites = Site.search([('type', '=', 'cassini')])
            if not sites:
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
                sites = Site.search([('type', '=', 'cassini')])
            if len(sites) == 1:
                Site.create([{
                            'name': 'Cassini Secondary',
                            'type': 'cassini',
                            'url': 'http://secondary.localhost/',
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
            'button', name='Cassini URI Wizard', exact=True).click()

        expect(page.get_by_role(
            'dialog', name='Cassini URI Wizard')).to_be_visible()
        expect(page.locator('.vs-wizard')).to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(0)
        expect(page.get_by_role(
            'heading', name='What do you want to do?')).to_be_visible()
        sites = page.locator('[data-field="sites"] select')
        expect(sites.locator('option')).not_to_have_count(0)
        selected = sites.locator('option').first.get_attribute('value')
        with page.expect_response(
                lambda response: '/wizard/field/sites' in response.url):
            sites.select_option(selected)

        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-wizard')).to_be_visible()
        selected_sites = page.locator(
            '[data-field="sites"] select option:checked')
        expect(selected_sites).to_have_count(1)
        expect(selected_sites).to_have_attribute('value', selected)
        page.get_by_role('button', name='Cancel', exact=True).click()
        expect(page.locator('.vs-wizard')).not_to_be_visible()

        page.get_by_role(
            'button',
            name='Cassini URI Wizard Window',
            exact=True).click()
        expect(page.get_by_role(
            'dialog',
            name='Cassini URI Wizard Window')).to_have_count(0)
        expect(page.locator(
            '.vs-tab',
            has_text='Cassini URI Wizard Window')).to_be_visible()
        expect(page.locator('.vs-wizard')).to_be_visible()
        page.get_by_role('button', name='Cancel', exact=True).click()
        expect(page.locator('.vs-wizard')).not_to_be_visible()

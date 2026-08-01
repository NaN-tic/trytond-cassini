import json

from dominate.tags import div, span
from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser
from trytond.modules.cassini.state import register_state_component


class TestCustomComponent(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @staticmethod
    def counter(state, context):
        return div(
            span(
                str(state.get('value', 0)),
                data_testid='counter-value'),
            span(
                context['user'].login,
                data_testid='counter-user'))

    @classmethod
    def setUpClass(cls):
        register_state_component('playwright-counter', cls.counter)
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
        root_url = (
            f'{self.base_url}/{self.database}/cassini')
        page.goto(root_url + '/', wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()

        component_url = root_url + '/component/playwright-counter'
        response = page.context.request.get(component_url)
        self.assertTrue(response.ok)
        self.assertIn('data-testid="counter-value">0<', response.text())

        update = page.context.request.post(
            component_url + '/state',
            form={'payload': json.dumps({'value': 7})})
        self.assertTrue(update.ok)
        self.assertIn('data-testid="counter-value">7<', update.text())

        page.goto(component_url, wait_until='domcontentloaded')
        expect(page.get_by_test_id('counter-value')).to_have_text('7')
        expect(page.get_by_test_id('counter-user')).to_have_text(self.user)
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_test_id('counter-value')).to_have_text('7')

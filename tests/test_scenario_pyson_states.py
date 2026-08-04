from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestPysonStates(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')
            PysonState = pool.get('cassini.test.pyson_state')

            record, = PysonState.create([{
                        'street_area_value': 'Central',
                        }])
            view, = View.create([{
                        'model': 'cassini.test.pyson_state',
                        'type': 'form',
                        'data': (
                            '<form col="2">'
                            '<label name="street_value"/>'
                            '<field name="street_value"/>'
                            '<label name="street_name_value"/>'
                            '<field name="street_name_value"/>'
                            '<label name="street_number_value"/>'
                            '<field name="street_number_value"/>'
                            '<label name="street_area_value"/>'
                            '<field name="street_area_value"/>'
                            '</form>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini PYSON States',
                        'res_model': 'cassini.test.pyson_state',
                        'domain': '[["id", "=", %d]]' % record.id,
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini PYSON States',
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
            'button', name='Cassini PYSON States', exact=True).click()

        street = page.locator(
            '[data-field="street_value"] textarea')
        expect(page.locator(
            '[data-field="street_name_value"]')).to_be_visible()
        expect(page.locator(
            '[data-field="street_number_value"] input')).to_be_enabled()
        self.assertIsNone(page.locator(
            '[data-field="street_area_value"] input').get_attribute(
                'required'))
        street_name = page.locator(
            '[data-field="street_name_value"] input')
        with page.expect_response(
                lambda response: '/field/street_name_value' in response.url):
            street_name.fill('Named Street')
            street_name.blur()
        street.fill('Main Street')
        with page.expect_response(
                lambda response: '/field/street_value' in response.url):
            street.blur()
        expect(page.locator(
            '[data-field="street_name_value"]')).to_be_visible()
        expect(page.locator(
            '[data-field="street_number_value"] input')).to_be_disabled()
        expect(page.locator(
            '[data-field="street_area_value"] input')).to_have_attribute(
                'required', 'required')
        expect(page.get_by_text(
            'Street Area', exact=True)).to_have_css('font-weight', '700')
        street_name = page.locator(
            '[data-field="street_name_value"] input')
        with page.expect_response(
                lambda response: '/field/street_name_value' in response.url):
            street_name.fill('')
            street_name.blur()
        expect(page.locator(
            '[data-field="street_name_value"]')).to_be_hidden()
        expect(page.get_by_text('Street Name', exact=True)).to_be_hidden()

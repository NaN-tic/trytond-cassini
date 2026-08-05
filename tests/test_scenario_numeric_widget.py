from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestNumericWidget(WebTestCase):
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
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')
            Widget = pool.get('cassini.test.widget')

            Widget.create([{
                        'char_value': 'Numeric Widget',
                        'float_value': 1234567.5,
                        'integer_value': 1234567,
                        'monetary_value': Decimal('1234567.50'),
                        'numeric_value': Decimal('1234567.50'),
                        }])
            view, = View.create([{
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form cursor="char_value">'
                            '<field name="char_value"/>'
                            '<field name="integer_value"/>'
                            '<field name="float_value"/>'
                            '<field name="numeric_value"/>'
                            '<field name="monetary_value" readonly="1"/>'
                            '</form>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Numeric Widget',
                        'res_model': 'cassini.test.widget',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Numeric Widget',
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
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            page.get_by_role(
                'button', name='Cassini Numeric Widget', exact=True).click()

        integer = page.locator('[data-field="integer_value"]')
        integer_display = integer.locator('[data-numeric-display]')
        integer_editor = integer.locator('[data-numeric-editor]')
        expect(integer_display).to_be_visible()
        expect(integer_display).to_have_attribute('type', 'text')
        expect(integer_display).not_to_have_attribute('readonly', '')
        expect(integer_display).to_have_value('1,234,567')
        expect(integer_editor).to_be_hidden()
        expect(integer_editor).to_have_attribute('type', 'number')

        integer_display.click()
        expect(integer_display).to_be_hidden()
        expect(integer_editor).to_be_visible()
        expect(integer_editor).to_be_focused()
        expect(integer_editor).to_have_value('1234567')
        with page.expect_response(
                lambda response: '/field/integer_value' in response.url):
            integer_editor.press('ArrowUp')
            integer_editor.blur()
        expect(integer_editor).to_be_hidden()
        expect(integer_display).to_be_visible()
        expect(integer_display).to_have_value('1,234,568')

        float_ = page.locator('[data-field="float_value"]')
        expect(float_.locator('[data-numeric-display]')).to_have_value(
            '1,234,567.5')
        expect(float_.locator('[data-numeric-editor]')).to_be_hidden()

        numeric = page.locator('[data-field="numeric_value"]')
        expect(numeric.locator('[data-numeric-display]')).to_have_value(
            '1,234,567.50')
        expect(numeric.locator('[data-numeric-editor]')).to_be_hidden()

        readonly = page.locator('[data-field="monetary_value"]')
        expect(readonly.locator('[data-numeric-display]')).to_be_visible()
        expect(readonly.locator(
            '[data-numeric-display]')).to_have_attribute(
                'readonly', 'readonly')
        expect(readonly.locator('[data-numeric-display]')).to_have_value(
            '1,234,567.50')
        expect(readonly.locator('[data-numeric-editor]')).to_have_count(0)

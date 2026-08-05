from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestURLWidget(WebTestCase):
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
                        'callto_value': '+34930000000',
                        'char_value': 'URL Widget',
                        'email_value': 'url@example.test',
                        'sip_value': 'url@example.test',
                        }])
            view, = View.create([{
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form>'
                            '<field name="url_value" widget="url"/>'
                            '<field name="email_value" widget="email" '
                            'readonly="1"/>'
                            '<field name="callto_value" widget="callto"/>'
                            '<field name="sip_value" widget="sip"/>'
                            '<field name="readonly_url_value" widget="url"/>'
                            '</form>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini URL Widget',
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
                        'name': 'Cassini URL Widget',
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
                'button', name='Cassini URL Widget', exact=True).click()

        url = page.locator('[data-field="url_value"]')
        url_input = url.locator('[data-url-input]')
        url_open = url.locator('[data-url-open]')
        expect(url_input).to_have_attribute('type', 'url')
        expect(url_open).to_be_hidden()
        expect(url_open).not_to_have_attribute('href', '')
        expect(url_open).to_have_attribute('target', '_blank')
        expect(url_open).to_have_attribute('rel', 'noreferrer noopener')
        expect(url_open.locator(
            'img[src$="tryton-public.svg"]')).to_be_attached()

        with page.expect_response(
                lambda response: '/field/url_value' in response.url):
            url_input.fill('https://example.test/updated')
        expect(url_open).to_be_visible()
        expect(url_open).to_have_attribute(
            'href', 'https://example.test/updated')

        protocols = {
            'email_value': ('email', 'mailto:url@example.test'),
            'callto_value': ('url', 'callto:+34930000000'),
            'sip_value': ('url', 'sip:url@example.test'),
            }
        for name, (input_type, href) in protocols.items():
            field = page.locator('[data-field="%s"]' % name)
            expect(field.locator('[data-url-input]')).to_have_attribute(
                'type', input_type)
            expect(field.locator('[data-url-open]')).to_have_attribute(
                'href', href)

        readonly_email = page.locator(
            '[data-field="email_value"] [data-url-input]')
        expect(readonly_email).to_have_attribute('readonly', 'readonly')
        expect(readonly_email).not_to_have_attribute('disabled', '')
        expect(readonly_email).not_to_have_attribute('hx-post', '')

        readonly_url = page.locator('[data-field="readonly_url_value"]')
        readonly_url_input = readonly_url.locator('[data-url-input]')
        readonly_url_open = readonly_url.locator('[data-url-open]')
        expect(readonly_url_input).to_have_attribute('readonly', 'readonly')
        expect(readonly_url_input).not_to_have_attribute('disabled', '')
        expect(readonly_url_input).not_to_have_attribute('hx-post', '')
        expect(readonly_url_open).to_be_visible()
        expect(readonly_url_open).to_have_attribute(
            'href', 'https://readonly.example.test')

        page.get_by_role('button', name='Save', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(url_input).to_have_value('https://example.test/updated')
        expect(url_open).to_have_attribute(
            'href', 'https://example.test/updated')

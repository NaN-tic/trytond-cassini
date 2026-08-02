from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestUnsavedNavigation(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            group, = Group.create([{
                        'name': 'Original Navigation Group',
                        }])
            action, = ActionWindow.create([{
                        'name': 'Unsaved Navigation',
                        'res_model': 'res.group',
                        'domain': '[["id", "=", %d]]' % group.id,
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Unsaved Navigation',
                        'action': str(action),
                        }])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @staticmethod
    def switch_view(page, name):
        switch = page.get_by_label('Switch view')
        expect(switch).to_have_attribute('data-next-view', name.lower())
        switch.click()

    @staticmethod
    def edit_name(page, value):
        name = page.locator('[data-field="name"] input')
        name.press('Control+A')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            name.press_sequentially(value)
        expect(name).to_have_value(value)
        return name

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
            'button', name='Unsaved Navigation', exact=True).click()

        self.switch_view(page, 'Form')
        name = self.edit_name(page, 'Discarded Navigation Group')
        self.switch_view(page, 'Tree')

        dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text(
                'Discarded Navigation Group',
                exact=True)).to_be_visible()
        expect(dialog.get_by_text(
                '1 modified field in 1 record',
                exact=True)).to_be_visible()
        expect(dialog.get_by_text(
                'Save validates the record and writes the changes '
                'to Tryton.',
                exact=True)).to_be_visible()
        dialog.get_by_role('button', name='Cancel').click()
        expect(dialog).not_to_be_visible()
        expect(name).to_have_value('Discarded Navigation Group')

        self.switch_view(page, 'Tree')
        dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        dialog.get_by_role(
            'button', name='Switch without saving').click()
        expect(dialog).not_to_be_visible()
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'tree')
        expect(page.get_by_text(
                'Original Navigation Group', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Discarded Navigation Group', exact=True)).to_have_count(0)

        self.switch_view(page, 'Form')
        self.edit_name(page, 'Saved Navigation Group')
        self.switch_view(page, 'Tree')
        dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        with page.expect_response(
                lambda response: '/leave/switch-view' in response.url
                ) as response_info:
            dialog.get_by_role(
                'button', name='Save and switch').click()
        response_markup = response_info.value.text()
        self.assertIn('id="modal"', response_markup)
        self.assertNotIn('Unsaved changes', response_markup)
        expect(dialog).not_to_be_visible()
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'tree')
        expect(page.get_by_text(
                'Saved Navigation Group', exact=True)).to_be_visible()

        self.switch_view(page, 'Form')
        name = self.edit_name(page, 'Saved While Closing')
        page.locator('.vs-tab-close').click()
        dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='Cancel').click()
        expect(page.locator('.vs-tab')).to_have_count(1)
        expect(name).to_have_value('Saved While Closing')

        page.locator('.vs-tab-close').click()
        with page.expect_response(
                lambda response: '/leave/close-tab' in response.url):
            page.get_by_role(
                'alertdialog', name='Unsaved changes').get_by_role(
                    'button', name='Save and close').click()
        expect(page.locator('.vs-tab')).to_have_count(0)

        page.get_by_role(
            'button', name='Unsaved Navigation', exact=True).click()
        expect(page.get_by_text(
                'Saved While Closing', exact=True)).to_be_visible()

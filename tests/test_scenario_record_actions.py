from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestRecordActions(WebTestCase):
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

            action, = ActionWindow.create([{
                        'name': 'Cassini Record Actions',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Cassini Record Actions',
                        'action': str(action),
                        }])
            Group.create([{'name': 'Cassini Action Group'}])
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
            'button', name='Cassini Record Actions',
            exact=True).click()

        group_name = page.get_by_text(
            'Cassini Action Group', exact=True)
        expect(group_name).to_have_count(1)
        rows = page.locator('.vs-row')
        initial_rows = rows.count()
        window_menu = page.locator('details.vs-window-menu')
        expect(window_menu.locator('.vs-window-title')).to_contain_text(
            'Cassini Record Actions')
        window_menu.locator('.vs-window-title').click()
        expect(page.locator('.vs-toolbar')).to_have_css('z-index', '150')
        expect(window_menu.locator(
            '.vs-window-menu-list')).to_have_css('z-index', '155')
        window_menu.locator('.vs-window-title').click()
        group_name.locator('xpath=ancestor::tr').get_by_role(
            'checkbox', name='Select record').check()
        window_menu.locator('.vs-window-title').click()
        window_menu.get_by_role(
            'menuitem', name='Duplicate', exact=True).click()
        expect(rows).to_have_count(initial_rows + 1)

        window_menu.locator('.vs-window-title').click()
        with page.expect_download() as download_info:
            window_menu.get_by_role(
                'menuitem', name='Export selected fields',
                exact=True).click()
        download = download_info.value
        self.assertEqual(download.suggested_filename, 'res_group.csv')

        window_menu.locator('.vs-window-title').click()
        window_menu.get_by_role(
            'menuitem', name='Delete', exact=True).click()
        confirmation = page.get_by_role(
            'alertdialog', name='Confirm action')
        expect(confirmation).to_contain_text(
            'Delete the selected records?')
        confirmation.get_by_role(
            'button', name='Continue', exact=True).click()
        expect(rows).to_have_count(initial_rows)

        window_menu.locator('.vs-window-title').click()
        with page.expect_response(
                lambda response: response.url.endswith('/import')):
            window_menu.locator(
                '.vs-import-form input[type="file"]').set_input_files({
                    'name': 'groups.csv',
                    'mimeType': 'text/csv',
                    'buffer': b'name\nCassini Imported Group\n',
                    })
        expect(page.get_by_text(
                'Cassini Imported Group', exact=True)).to_be_visible()
        expect(rows).to_have_count(initial_rows + 1)

        switch = page.get_by_label('Switch view')
        expect(switch).to_have_attribute('data-next-view', 'form')
        switch.click()
        name = page.locator('[data-field="name"] input')
        original_name = name.input_value()
        name.press('Control+A')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            name.press_sequentially('Unsaved Action Group')
        expect(name).to_have_value('Unsaved Action Group')

        page.get_by_role(
            'button', name='Reload/Undo', exact=True).click()
        confirmation = page.get_by_role(
            'alertdialog', name='Confirm action')
        expect(confirmation).to_contain_text(
            'Discard the unsaved changes to this record?')
        confirmation.get_by_role(
            'button', name='Continue', exact=True).click()
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    original_name)

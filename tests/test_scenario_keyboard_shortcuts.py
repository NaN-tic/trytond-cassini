from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestKeyboardShortcuts(WebTestCase):
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

            Group.create([
                    {'name': 'Keyboard Shortcut Alpha'},
                    {'name': 'Keyboard Shortcut Beta'},
                    ])
            actions = ActionWindow.create([
                    {
                        'name': 'Keyboard Shortcuts',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        },
                    {
                        'name': 'Keyboard Shortcuts Secondary',
                        'res_model': 'res.user',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        },
                    ])
            Menu.create([
                    {
                        'name': action.name,
                        'action': str(action),
                        }
                    for action in actions])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @browser()
    def test(self, page: Page):
        def press_shortcut(
                key, code, *, alt=False, ctrl=False, shift=False):
            page.locator('body').dispatch_event('keydown', {
                    'key': key,
                    'code': code,
                    'altKey': alt,
                    'ctrlKey': ctrl,
                    'shiftKey': shift,
                    'metaKey': False,
                    })

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
                'button', name='Keyboard Shortcuts', exact=True).click()
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            page.get_by_role(
                'button', name='Keyboard Shortcuts Secondary',
                exact=True).click()
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts Secondary')

        with page.expect_response(
                lambda response:
                '/cassini/tab/' in response.url
                and not response.url.endswith('/close')):
            press_shortcut('Tab', 'Tab', alt=True)
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts')
        with page.expect_response(
                lambda response:
                '/cassini/tab/' in response.url
                and not response.url.endswith('/close')):
            page.get_by_role(
                'tab', name='Keyboard Shortcuts Secondary',
                exact=True).click()
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts Secondary')
        with page.expect_response(
                lambda response:
                '/cassini/tab/' in response.url
                and not response.url.endswith('/close')):
            press_shortcut('Tab', 'Tab', alt=True, shift=True)
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts')

        page.get_by_label('Switch view').focus()
        with page.expect_response(
                lambda response: response.url.endswith('/close')):
            press_shortcut('w', 'KeyW', alt=True)
        expect(page.locator('.vs-tab')).to_have_count(1)
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts Secondary')
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            page.get_by_role(
                'button', name='Keyboard Shortcuts', exact=True).click()
        with page.expect_response(
                lambda response: response.url.endswith('/close')):
            page.get_by_label(
                'Close Keyboard Shortcuts Secondary').click()
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts')

        switch = page.get_by_label('Switch view')
        switch.focus()
        press_shortcut('l', 'KeyL', ctrl=True)
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'form')

        page.get_by_label('Switch view').focus()
        press_shortcut('f', 'KeyF', ctrl=True)
        search = page.locator('.vs-search-input')
        expect(search).to_be_focused()

        page.get_by_label('Switch view').focus()
        press_shortcut('k', 'KeyK', ctrl=True)
        expect(page.locator('[data-global-search-input]')).to_be_focused()

        page.get_by_label('Switch view').focus()
        press_shortcut('F1', 'F1')
        dialog = page.get_by_role(
            'dialog', name='Keyboard shortcuts')
        expect(dialog).to_be_visible()
        expect(dialog.locator('kbd')).to_have_count(20)
        expect(dialog.get_by_text('Ctrl+Shift+D', exact=True)).to_be_visible()
        expect(dialog.get_by_text('Alt+Shift+Tab', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='Close').click()

        page.get_by_label('Switch view').focus()
        press_shortcut('l', 'KeyL', ctrl=True)
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'form')
        page.get_by_label('Switch view').focus()
        press_shortcut('F1', 'F1', ctrl=True)
        expect(page.locator('html')).to_have_class(
            'vs-accesskeys')
        field = page.locator('.vs-field[data-accesskey]').first
        expect(field).to_be_visible()
        expect(field.locator(
                'input, select, textarea').first).to_have_attribute(
                    'accesskey', field.get_attribute('data-accesskey'))

        page.get_by_label('Switch view').focus()
        press_shortcut('e', 'KeyE', ctrl=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="action"]')
            ).to_have_attribute('open', '')
        press_shortcut('r', 'KeyR', ctrl=True, shift=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="relate"]')
            ).to_have_attribute('open', '')
        press_shortcut('p', 'KeyP', ctrl=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="print"]')
            ).to_have_attribute('open', '')

        page.get_by_label('Switch view').focus()
        with page.expect_response(
                lambda response: response.url.endswith('/duplicate')):
            press_shortcut('d', 'KeyD', ctrl=True, shift=True)
        page.get_by_label('Switch view').focus()
        press_shortcut('l', 'KeyL', ctrl=True)
        expect(page.locator('.vs-row')).to_have_count(5)

        page.get_by_label('Switch view').focus()
        press_shortcut('d', 'KeyD', ctrl=True)
        confirmation = page.get_by_role(
            'alertdialog', name='Confirm action')
        expect(confirmation).to_be_visible()
        confirmation.get_by_role('button', name='Cancel').click()

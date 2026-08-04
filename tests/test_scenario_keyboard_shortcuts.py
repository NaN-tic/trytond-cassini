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
                key, code, *, target=None, alt=False, ctrl=False,
                shift=False):
            event_target = (
                target if target is not None else page.locator('body'))
            event_target.dispatch_event('keydown', {
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
            press_shortcut('PageDown', 'PageDown', alt=True)
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
            press_shortcut('PageUp', 'PageUp', alt=True)
        expect(page.locator('.vs-tab-active')).to_contain_text(
            'Keyboard Shortcuts')

        page.get_by_label('Switch view').click()
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'form')
        close_input = page.locator('[data-field="name"] input')
        with page.expect_response(
                lambda response: response.url.endswith('/close')):
            press_shortcut(
                'w', 'KeyW', target=close_input, alt=True)
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

        form_input = page.locator('[data-field="name"] input')
        press_shortcut(
            'f', 'KeyF', target=form_input, ctrl=True)
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
        expect(dialog.get_by_text('Alt+PageUp', exact=True)).to_be_visible()
        expect(dialog.get_by_text('Alt+PageDown', exact=True)).to_be_visible()
        expect(dialog.get_by_text(
            'Global search', exact=True)).to_be_visible()
        expect(dialog.get_by_text(
            'Global search or start a new assistant conversation',
            exact=True)).to_have_count(0)
        dialog.get_by_role('button', name='Close').click()

        page.get_by_text(
            'Keyboard Shortcut Alpha', exact=True).dblclick()
        expect(page.locator('.vs-screen')).to_have_attribute(
            'data-view', 'form')
        form_input = page.locator('[data-field="name"] input')
        press_shortcut(
            'F1', 'F1', target=form_input, ctrl=True)
        expect(page.locator('html')).to_have_class(
            'vs-accesskeys')
        field = page.locator('.vs-field[data-accesskey]').first
        expect(field).to_be_visible()
        expect(field.locator(
                'input, select, textarea').first).to_have_attribute(
                    'accesskey', field.get_attribute('data-accesskey'))

        initial_name = form_input.input_value()
        with page.expect_response(
                lambda response: response.url.endswith('/record/next')):
            press_shortcut(
                'ArrowDown', 'ArrowDown', target=form_input, ctrl=True)
        form_input = page.locator('[data-field="name"] input')
        self.assertNotEqual(form_input.input_value(), initial_name)
        with page.expect_response(
                lambda response: response.url.endswith('/record/previous')):
            press_shortcut(
                'ArrowUp', 'ArrowUp', target=form_input, ctrl=True)
        form_input = page.locator('[data-field="name"] input')
        expect(form_input).to_have_value(initial_name)

        press_shortcut(
            't', 'KeyT', target=form_input, ctrl=True, shift=True)
        attachment_popup = page.locator('details.vs-attachment-popup')
        expect(attachment_popup).to_have_attribute('open', '')
        attachment_popup.locator('summary').click()

        with page.expect_response(
                lambda response: '/related/notes' in response.url):
            press_shortcut(
                'o', 'KeyO', target=form_input, ctrl=True, shift=True)
        note_dialog = page.locator('.vs-relation-record-dialog')
        expect(note_dialog).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith('/close')):
            note_dialog.get_by_role(
                'button', name='Cancel', exact=True).click()
        expect(note_dialog).to_have_count(0)

        press_shortcut('e', 'KeyE', target=form_input, ctrl=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="action"]')
            ).to_have_attribute('open', '')
        press_shortcut(
            'r', 'KeyR', target=form_input, ctrl=True, shift=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="relate"]')
            ).to_have_attribute('open', '')
        press_shortcut('p', 'KeyP', target=form_input, ctrl=True)
        expect(page.locator(
            'details.vs-action-popup[data-action-category="print"]')
            ).to_have_attribute('open', '')

        press_shortcut('d', 'KeyD', target=form_input, ctrl=True)
        confirmation = page.get_by_role(
            'alertdialog', name='Confirm action')
        expect(confirmation).to_be_visible()
        confirmation.get_by_role('button', name='Cancel').click()

        duplicate_name = 'Saved Before Keyboard Shortcut Duplicate'
        form_input.fill(duplicate_name)
        with page.expect_response(
                lambda response: response.url.endswith('/duplicate')):
            press_shortcut(
                'd', 'KeyD', target=form_input, ctrl=True, shift=True)
        unsaved_dialog = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(unsaved_dialog).to_be_visible()
        expect(unsaved_dialog).to_contain_text(
            'Choose what to do before you duplicate this record.')
        expect(unsaved_dialog.get_by_role(
            'button', name='Duplicate without saving')).to_be_visible()
        with page.expect_response(
                lambda response: '/leave/duplicate' in response.url
                ) as duplicate_response:
            unsaved_dialog.get_by_role(
                'button', name='Save and duplicate').click()
        duplicate_markup = duplicate_response.value.text()
        self.assertNotIn(
            'vs-notice-error', duplicate_markup, duplicate_markup)
        expect(unsaved_dialog).to_have_count(0)
        page.get_by_label('Switch view').focus()
        press_shortcut('l', 'KeyL', ctrl=True)
        expect(page.locator('.vs-row')).to_have_count(5)
        expect(page.locator(
            '.vs-row', has_text=duplicate_name)).to_have_count(2)

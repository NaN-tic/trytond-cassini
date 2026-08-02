from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.pyson import Eval, PYSONEncoder
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
            ActionKeyword = pool.get('ir.action.keyword')
            Attachment = pool.get('ir.attachment')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Note = pool.get('ir.note')
            Site = pool.get('www.site')

            action, = ActionWindow.create([{
                        'name': 'Cassini Record Actions',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            related_action, = ActionWindow.create([{
                        'name': 'Cassini Related Groups',
                        'res_model': 'res.group',
                        'domain': PYSONEncoder().encode([
                                ('id', '=', Eval('active_id', -1)),
                                ]),
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionKeyword.create([{
                        'keyword': 'form_relate',
                        'model': 'res.group,-1',
                        'action': related_action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Record Actions',
                        'action': str(action),
                        }])
            group, = Group.create([{'name': 'Cassini Action Group'}])
            Attachment.create([{
                        'name': 'cassini-action.txt',
                        'type': 'data',
                        'data': b'Cassini attachment',
                        'resource': str(group),
                        }])
            note, = Note.create([{
                        'message': 'Cassini note',
                        'resource': str(group),
                        }])
            Note.write([note], {'unread': True})
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
        expect(window_menu.locator('.vs-window-title')).to_have_attribute(
            'aria-label', 'Window actions: Cassini Record Actions')
        expect(page.locator('.vs-window-heading-label')).to_have_text(
            'Cassini Record Actions')
        window_menu.locator('.vs-window-title').click()
        expect(page.locator('.vs-toolbar')).to_have_css('z-index', '150')
        expect(window_menu.locator(
            '.vs-window-menu-list')).to_have_css('z-index', '155')
        window_menu.locator('.vs-window-title').click()
        group_row = group_name.locator('xpath=ancestor::tr')
        group_position = group_row.evaluate(
            'row => Array.from(row.parentElement.children).indexOf(row) + 1')
        with page.expect_response(
                lambda response: '/select?row=true' in response.url):
            group_name.click()
        expect(group_row.get_by_role(
            'checkbox', name='Select record')).to_be_checked()
        expect(page.get_by_role(
            'group', name='Record navigation')).to_contain_text(
                '%s/%s' % (group_position, initial_rows))

        attachment_popup = page.locator('details.vs-attachment-popup')
        expect(attachment_popup.locator(
            '.vs-resource-badge')).to_have_text('1')
        attachment_popup.locator('summary').click()
        expect(attachment_popup.get_by_role(
            'menuitem', name='cassini-action.txt')).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/attachments/upload')):
            attachment_popup.locator(
                '[data-attachment-input]').set_input_files({
                    'name': 'second.txt',
                    'mimeType': 'text/plain',
                    'buffer': b'Second attachment',
                    })
        attachment_popup = page.locator('details.vs-attachment-popup')
        expect(attachment_popup.locator(
            '.vs-resource-badge')).to_have_text('2')
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/attachments/upload')):
            attachment_popup.locator('summary').evaluate(
                '''summary => {
                    const transfer = new DataTransfer();
                    transfer.items.add(new File(
                        ["Dropped attachment"], "dropped.txt",
                        {type: "text/plain"}));
                    summary.dispatchEvent(new DragEvent("drop", {
                        bubbles: true,
                        cancelable: true,
                        dataTransfer: transfer,
                    }));
                }''')
        attachment_popup = page.locator('details.vs-attachment-popup')
        expect(attachment_popup.locator(
            '.vs-resource-badge')).to_have_text('3')
        attachment_popup.locator('summary').click()
        attachment_popup.get_by_role(
            'menuitem', name='Preview', exact=True).click()
        preview = page.get_by_role(
            'dialog', name='Attachment preview')
        expect(preview).to_contain_text('cassini-action.txt')
        preview.get_by_role('button', name='Close').click()
        attachment_popup.locator('summary').click()
        attachment_popup.get_by_role(
            'menuitem', name='Manage...', exact=True).click()
        attachment_dialog = page.locator('.vs-relation-record-dialog')
        expect(attachment_dialog).to_be_visible()
        expect(attachment_dialog).to_contain_text(
            'Attachments (Cassini Action Group)')
        expect(attachment_dialog.get_by_role(
            'group', name='Resource actions')).to_be_visible()
        expect(attachment_dialog.get_by_role(
            'button', name='New', exact=True)).to_be_enabled()
        attachment_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()

        notes = page.locator('[data-shortcut-action="note"]')
        expect(notes.locator('.vs-resource-badge')).to_have_text('1/1')
        notes.click()
        note_dialog = page.locator('.vs-relation-record-dialog')
        expect(note_dialog).to_be_visible()
        expect(note_dialog).to_contain_text(
            'Notes (Cassini Action Group)')
        expect(note_dialog.get_by_role(
            'button', name='New', exact=True)).to_be_enabled()
        note_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()

        relate = page.locator(
            'details.vs-action-popup[data-action-category="relate"]')
        relate.locator('summary').click()
        relate.get_by_role(
            'menuitem', name='Cassini Related Groups').click()
        expect(page.locator(
            '.vs-tab-active .vs-tab-title')).to_have_text(
                'Cassini Related Groups (Cassini Action Group)')
        page.locator('.vs-tab-active .vs-tab-close').click()

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

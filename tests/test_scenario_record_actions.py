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
            Group.create([{
                        'name': 'Cassini Empty Attachment Group',
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
        expect(page.locator('.vs-toolbar')).to_have_css(
            'border-bottom-width', '0px')
        expect(page.locator('.vs-toolbar')).to_have_css(
            'background-color', 'rgb(232, 239, 235)')
        expect(page.locator('.vs-search-toolbar')).to_have_css(
            'border-top-width', '0px')
        expect(page.locator('.vs-search-toolbar')).to_have_css(
            'background-color', 'rgb(255, 255, 255)')
        expect(page.locator('#workspace-tabs .vs-tab-active')).to_have_css(
            'background-color', 'rgb(232, 239, 235)')
        main_box = page.locator('.vs-main').bounding_box()
        panel_box = page.locator('#active-panel').bounding_box()
        self.assertAlmostEqual(
            panel_box['y'] + panel_box['height'],
            main_box['y'] + main_box['height'], delta=1)
        table_top = page.locator('.vs-table-wrap').bounding_box()['y']
        toolbar_height = page.locator('.vs-toolbar').bounding_box()['height']
        window_menu.locator('.vs-window-title').click()
        expect(page.locator('.vs-toolbar')).to_have_css('z-index', '150')
        expect(window_menu.locator(
            '.vs-window-menu-list')).to_have_css('z-index', '155')
        expect(window_menu.locator(
            '.vs-window-menu-list')).to_have_css('position', 'absolute')
        self.assertAlmostEqual(
            page.locator('.vs-table-wrap').bounding_box()['y'],
            table_top, delta=1)
        self.assertAlmostEqual(
            page.locator('.vs-toolbar').bounding_box()['height'],
            toolbar_height, delta=1)
        window_menu.locator('.vs-window-title').click()

        empty_group = page.get_by_text(
            'Cassini Empty Attachment Group', exact=True)
        empty_group.click()
        empty_attachments = page.locator('details.vs-attachment-popup')
        empty_attachments.locator('summary').click()
        empty_preview = empty_attachments.get_by_role(
            'menuitem', name='Preview', exact=True)
        expect(empty_preview).to_be_enabled()
        empty_preview.click()
        preview = page.locator('aside.vs-attachment-preview')
        expect(preview).to_contain_text('No attachments')
        preview.get_by_role('button', name='Close', exact=True).click()

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
        preview_menu_item = attachment_popup.get_by_role(
            'menuitem', name='Preview', exact=True)
        expect(preview_menu_item.locator(
            '.vs-attachment-preview-toggle')).to_have_class(
                'vs-attachment-preview-toggle')
        preview_menu_item.click()
        preview = page.locator('aside.vs-attachment-preview')
        expect(preview).to_be_visible()
        expect(preview.get_by_role(
            'heading', name='Attachment preview')).to_have_count(0)
        expect(preview).to_have_css('resize', 'horizontal')
        expect(preview).to_have_css('direction', 'rtl')
        expect(preview).to_have_css('background-color', 'rgb(255, 255, 255)')
        preview_box = preview.bounding_box()
        panel_box = page.locator('#active-panel').bounding_box()
        self.assertAlmostEqual(
            preview_box['y'] + preview_box['height'],
            panel_box['y'] + panel_box['height'], delta=1)
        preview_width = preview.bounding_box()['width']
        preview.evaluate('element => element.style.width = "28rem"')
        self.assertGreater(preview.bounding_box()['width'], preview_width)
        attachment_name = preview.get_by_role('heading', level=4)
        expect(attachment_name).to_be_visible()
        expect(attachment_name).to_have_css('text-align', 'center')
        expect(attachment_name).to_have_css('font-weight', '700')
        expect(preview.locator(
            '.vs-attachment-preview-toolbar')).to_have_css(
                'justify-content', 'center')
        close_button = preview.get_by_role('button', name='Close', exact=True)
        self.assertGreater(
            close_button.bounding_box()['x'],
            preview.locator(
                '.vs-attachment-preview-navigation').bounding_box()['x'])
        attachment_popup.locator('summary').click()
        expect(attachment_popup.get_by_role(
            'menuitem', name='Preview', exact=True).locator(
                '.vs-attachment-preview-toggle')).to_have_class(
                    'vs-attachment-preview-toggle '
                    'vs-attachment-preview-toggle-active')
        expect(attachment_popup.get_by_role(
            'menuitem', name='Preview', exact=True).locator(
                '.vs-attachment-preview-toggle')).to_have_css(
                    'background-color', 'rgb(31, 109, 93)')
        attachment_popup.locator('summary').click()
        expect(preview.locator(
            '.vs-attachment-preview-count')).to_have_text('1/3')
        preview.get_by_role('button', name='Next', exact=True).click()
        preview = page.locator('aside.vs-attachment-preview')
        expect(preview.locator(
            '.vs-attachment-preview-count')).to_have_text('2/3')
        preview.get_by_role('button', name='Close', exact=True).click()
        expect(page.locator('aside.vs-attachment-preview')).to_have_count(0)
        attachment_popup.locator('summary').click()
        attachment_popup.get_by_role(
            'menuitem', name='Manage...', exact=True).click()
        attachment_dialog = page.locator('.vs-relation-record-dialog')
        expect(attachment_dialog).to_be_visible()
        expect(attachment_dialog).to_contain_text(
            'Attachments (Cassini Action Group)')
        attachment_actions = attachment_dialog.get_by_role(
            'toolbar', name='Relation actions')
        for action in ('Switch', 'Previous', 'Next', 'New', 'Open',
                'Delete', 'Undelete'):
            expect(attachment_actions.get_by_role(
                'button', name=action, exact=True)).to_be_visible()
        expect(attachment_actions.get_by_role(
            'button', name='New', exact=True)).to_be_enabled()
        attachment_rows = attachment_dialog.locator(
            '.vs-x2many-content .vs-row')
        attachment_row_count = attachment_rows.count()
        attachment_actions.get_by_role(
            'button', name='New', exact=True).click()
        expect(attachment_rows).to_have_count(attachment_row_count + 1)
        expect(attachment_rows.last.get_by_role('textbox')).to_be_visible()
        attachment_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()

        notes = page.locator('[data-shortcut-action="note"]')
        expect(notes.locator('.vs-resource-badge')).to_have_text('1/1')
        notes.click()
        note_dialog = page.locator('.vs-relation-record-dialog')
        expect(note_dialog).to_be_visible()
        expect(note_dialog).to_contain_text(
            'Notes (Cassini Action Group)')
        note_actions = note_dialog.get_by_role(
            'toolbar', name='Relation actions')
        expect(note_actions.get_by_role(
            'button', name='New', exact=True)).to_be_enabled()
        expect(note_actions.get_by_role(
            'button', name='Open', exact=True)).to_be_enabled()
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
        window_menu.get_by_role(
            'menuitem', name='Export',
            exact=True).click()
        export_dialog = page.get_by_role(
            'dialog', name='CSV Export: Cassini Record Actions')
        expect(export_dialog).to_be_visible()
        expect(export_dialog.get_by_text(
            'All Fields', exact=True)).to_be_visible()
        expect(export_dialog.get_by_text(
            'Fields Selected', exact=True)).to_be_visible()
        expect(export_dialog.locator(
            '[data-csv-selected-field="name"]')).to_have_count(1)
        parent_field = export_dialog.locator(
            '[data-csv-field-choice][data-csv-field="parent"]')
        with page.expect_response(
                lambda response: '/csv/fields' in response.url):
            parent_field.locator(
                'xpath=ancestor::li[1]').locator(
                    '[data-csv-expand]').click()
        expect(parent_field.locator(
            'xpath=ancestor::li[1]').locator(
                ':scope > .vs-csv-field-children')).to_contain_text('Name')
        export_dialog.locator('[name="export_name"]').fill(
            'Cassini Group Export')
        with page.expect_response(
                lambda response: response.url.endswith('/export/save')):
            export_dialog.get_by_role(
                'button', name='Save Export', exact=True).click()
        export_dialog = page.get_by_role(
            'dialog', name='CSV Export: Cassini Record Actions')
        expect(export_dialog.get_by_role(
            'button', name='Cassini Group Export',
            exact=True)).to_be_visible()
        export_dialog.get_by_role(
            'button', name='Cassini Group Export', exact=True).click()
        export_dialog.get_by_text(
            'CSV Parameters', exact=True).click()
        export_dialog.locator('[name="delimiter"]').fill(';')
        with page.expect_download() as download_info:
            export_dialog.get_by_role(
                'button', name='Save As...', exact=True).click()
        download = download_info.value
        self.assertEqual(download.suggested_filename, 'res_group.csv')
        export_content = download.path().read_text()
        self.assertIn('Cassini Action Group', export_content)
        export_dialog.get_by_role(
            'button', name='Close', exact=True).click()

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
        window_menu.locator('.vs-window-menu-list').evaluate(
            'menu => { menu.scrollTop = menu.scrollHeight; }')
        window_menu.get_by_role(
            'menuitem', name='Import', exact=True).click()
        import_dialog = page.get_by_role(
            'dialog', name='CSV Import: Cassini Record Actions')
        expect(import_dialog).to_be_visible()
        import_dialog.locator('[name="file"]').set_input_files({
            'name': 'groups.csv',
            'mimeType': 'text/csv',
            'buffer': b'Name\nCassini Imported Group\n',
            })
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/import/autodetect')):
            import_dialog.get_by_role(
                'button', name='Auto-Detect', exact=True).click()
        expect(import_dialog.locator(
            '[data-csv-selected-field="name"]')).to_have_count(1)
        expect(import_dialog.locator('[name="skip"]')).to_have_value('1')
        with page.expect_response(
                lambda response: response.url.endswith('/import')):
            import_dialog.get_by_role(
                'button', name='Import', exact=True).click()
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

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser

from trytond.modules.cassini.views import parse_architecture


class TestViewsWidgets(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Group = pool.get('res.group')
            Lang = pool.get('ir.lang')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')
            Widget = pool.get('cassini.test.widget')

            english, = Lang.search([('code', '=', 'en')])
            Lang.write([english], {'date': '%d/%m/%Y'})

            first_group, second_group, = Group.create([
                    {'name': 'Widget Group One'},
                    {'name': 'Widget Group Two'},
                    ])
            Group.create([{
                        'name': (
                            'Very Long Widget Group Suggestion That Must '
                            'Stay on One Line'),
                        }])
            cls.today = date.today()
            cls.now = datetime.combine(cls.today, time(10, 30))
            Widget.create([
                    {
                        'binary_value': b'binary',
                        'binary_filename': 'binary.txt',
                        'boolean_value': True,
                        'callto_value': '+34930000000',
                        'char_value': 'Widget Alpha',
                        'color_value': '#336699',
                        'date_value': cls.today,
                        'datetime_value': cls.now,
                        'dict_value': {'key': 'value'},
                        'document_value': b'document',
                        'document_filename': 'document.txt',
                        'email_value': 'alpha@example.test',
                        'float_value': 3.5,
                        'html_value': '<p>Alpha</p>',
                        'image_value': b'image',
                        'integer_value': 7,
                        'many2many_value': [('add', [first_group.id])],
                        'many2one_value': first_group.id,
                        'multiselection_value': ('first', 'second'),
                        'numeric_value': Decimal('12.30'),
                        'one2many_value': [
                            ('create', [{'name': 'Alpha Child'}])],
                        'one2one_value': first_group.id,
                        'password_value': 'secret',
                        'progress_value': .65,
                        'pyson_value': '{}',
                        'reference_value': str(first_group),
                        'richtext_value': 'Rich Alpha',
                        'selection_value': 'draft',
                        'sip_value': 'alpha@example.test',
                        'text_value': 'Text Alpha',
                        'time_value': time(10, 30),
                        'timedelta_value': timedelta(hours=2),
                        'timestamp_value': cls.now,
                        'url_value': 'https://example.test/alpha',
                        },
                    {
                        'binary_value': b'beta',
                        'binary_filename': 'beta.txt',
                        'char_value': 'Widget Beta',
                        'date_value': cls.today,
                        'many2one_value': second_group.id,
                        'one2many_value': [
                            ('create', [
                                    {'name': 'Beta Child One'},
                                    {'name': 'Beta Child Two'},
                                    ])],
                        'one2one_value': second_group.id,
                        'reference_value': str(first_group),
                        'selection_value': 'draft',
                        'time_value': time(10, 30),
                        },
                    ])

            link_action, = ActionWindow.create([{
                        'name': 'Cassini Widget Link',
                        'res_model': 'cassini.test.widget',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ModelData.create([{
                        'module': 'cassini',
                        'fs_id': 'test_widget_link',
                        'model': 'ir.action.act_window',
                        'db_id': link_action.id,
                        'noupdate': True,
                        }])

            (
                tree_view, form_view, list_form_view, calendar_view,
                scan_view,
                ) = View.create([
                    {
                        'model': 'cassini.test.widget',
                        'type': 'tree',
                        'data': (
                            '<tree>'
                            '<field name="char_value"/>'
                            '<field name="binary_value" '
                            'filename="binary_filename"/>'
                            '<field name="datetime_value" widget="date"/>'
                            '<field name="datetime_value" widget="time"/>'
                            '<field name="many2one_value"/>'
                            '<field name="selection_value"/>'
                            '<field name="integer_value" optional="1">'
                            '<suffix name="integer_value" string=" units"/>'
                            '</field>'
                            '<button name="mark" string="Mark"/>'
                            '<button name="mark" string="Hidden Mark" '
                            'tree_invisible="1"/>'
                            '<button name="mark" string="Mark selected" '
                            'multiple="1"/>'
                            '</tree>'),
                        },
                    {
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form col="6" cursor="char_value">'
                            '<group id="payload" string="Payload" '
                            'expandable="1" col="4">'
                            '<field name="binary_value" widget="binary" '
                            'filename="binary_filename" '
                            'filename_visible="1" colspan="4"/>'
                            '<field name="boolean_value" widget="boolean"/>'
                            '</group>'
                            '<group id="unlimited" string="Unlimited" '
                            'col="-1" colspan="6">'
                            '<label name="callto_value"/>'
                            '<field name="callto_value" widget="callto"/>'
                            '<label name="email_value"/>'
                            '<field name="email_value" widget="email"/>'
                            '</group>'
                            '<label name="char_value"/>'
                            '<field name="char_value" widget="char"/>'
                            '<field name="color_value" widget="color"/>'
                            '<field name="date_value" widget="date"/>'
                            '<field name="datetime_value" widget="datetime"/>'
                            '<field name="dict_value" widget="dict"/>'
                            '<field name="document_value" widget="document" '
                            'filename="document_filename"/>'
                            '<field name="float_value" widget="float"/>'
                            '<field name="html_value" widget="html"/>'
                            '<field name="image_value" widget="image"/>'
                            '<field name="integer_value" widget="integer"/>'
                            '<field name="many2many_value" '
                            'widget="many2many"/>'
                            '<field name="many2one_value" widget="many2one"/>'
                            '<field name="multiselection_value" '
                            'widget="multiselection"/>'
                            '<field name="numeric_value" widget="numeric"/>'
                            '<field name="one2many_value" widget="one2many" '
                            'colspan="6"/>'
                            '<field name="one2one_value" widget="one2one"/>'
                            '<field name="password_value" widget="password"/>'
                            '<field name="progress_value" '
                            'widget="progressbar"/>'
                            '<field name="pyson_value" widget="pyson"/>'
                            '<field name="reference_value" '
                            'widget="reference"/>'
                            '<field name="richtext_value" widget="richtext"/>'
                            '<field name="selection_value" '
                            'widget="selection"/>'
                            '<field name="sip_value" widget="sip"/>'
                            '<field name="text_value" widget="text"/>'
                            '<field name="time_value" widget="time"/>'
                            '<field name="timedelta_value" '
                            'widget="timedelta"/>'
                            '<field name="timestamp_value"/>'
                            '<field name="url_value" widget="url"/>'
                            '<separator name="email_value" colspan="6"/>'
                            '<notebook colspan="6">'
                            '<page name="char_value">'
                            '<separator name="boolean_value"/>'
                            '</page>'
                            '</notebook>'
                            '<button name="change_character" '
                            'string="Change Character" type="instance" '
                            'icon="tryton-ok"/>'
                            '<link name="cassini.test_widget_link" '
                            'icon="tryton-open"/>'
                            '</form>'),
                        },
                    {
                        'model': 'cassini.test.widget',
                        'type': 'list-form',
                        'data': (
                            '<form>'
                            '<field name="char_value"/>'
                            '<field name="selection_value"/>'
                            '</form>'),
                        },
                    {
                        'model': 'cassini.test.widget',
                        'type': 'calendar',
                        'data': (
                            '<calendar dtstart="date_value" mode="month">'
                            '<field name="char_value"/>'
                            '</calendar>'),
                        },
                    {
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form scan_code="submit" col="2">'
                            '<field name="char_value"/>'
                            '<field name="selection_value"/>'
                            '</form>'),
                        },
                    ])

            (
                widgets_action, list_form_action, calendar_action,
                scan_action,
                ) = (
                ActionWindow.create([
                        {
                            'name': 'Cassini Widget Matrix',
                            'res_model': 'cassini.test.widget',
                            'domain': '[]',
                            'context': '{}',
                            'search_value': '[]',
                            },
                        {
                            'name': 'Cassini List Form',
                            'res_model': 'cassini.test.widget',
                            'domain': '[]',
                            'context': '{}',
                            'search_value': '[]',
                            },
                        {
                            'name': 'Cassini Calendar',
                            'res_model': 'cassini.test.widget',
                            'domain': '[]',
                            'context': '{}',
                            'search_value': '[]',
                            },
                        {
                            'name': 'Cassini Scan Code',
                            'res_model': 'cassini.test.widget',
                            'domain': '[]',
                            'context': '{}',
                            'search_value': '[]',
                            },
                        ]))
            for sequence, view in enumerate((tree_view, form_view), 1):
                ActionWindowView.create([{
                            'sequence': sequence,
                            'view': view.id,
                            'act_window': widgets_action.id,
                            }])
            ActionWindowView.create([
                    {
                        'sequence': 1,
                        'view': list_form_view.id,
                        'act_window': list_form_action.id,
                        },
                    {
                        'sequence': 1,
                        'view': calendar_view.id,
                        'act_window': calendar_action.id,
                        },
                    {
                        'sequence': 1,
                        'view': scan_view.id,
                        'act_window': scan_action.id,
                        },
                    ])
            Menu.create([
                    {
                        'name': 'Cassini Widget Matrix',
                        'action': str(widgets_action),
                        },
                    {
                        'name': 'Cassini List Form',
                        'action': str(list_form_action),
                        },
                    {
                        'name': 'Cassini Calendar',
                        'action': str(calendar_action),
                        },
                    {
                        'name': 'Cassini Scan Code',
                        'action': str(scan_action),
                        },
                    ])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @browser()
    def test(self, page: Page):
        architecture = parse_architecture({
                'arch': (
                    '<form><group name="char_value"/>'
                    '<separator name="email_value"/>'
                    '<notebook><page name="boolean_value"/></notebook>'
                    '<group name="char_value" string=""/></form>'),
                'fields': {
                    'boolean_value': {'string': 'Boolean'},
                    'char_value': {'string': 'Character'},
                    'email_value': {
                        'string': 'Email',
                        'states': '{"invisible": true}',
                        },
                    },
                })
        self.assertEqual(architecture[0].attrib['string'], 'Character')
        self.assertEqual(architecture[1].attrib['string'], 'Email')
        self.assertEqual(architecture[2][0].attrib['string'], 'Boolean')
        self.assertEqual(architecture[3].attrib['string'], '')
        self.assertEqual(
            architecture[1].attrib['states'], '{"invisible": true}')

        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        welcome_title = page.get_by_role(
            'heading', name='What do you want to do?')
        self.assertLessEqual(
            float(welcome_title.evaluate(
                'element => parseFloat(getComputedStyle(element).fontSize)')),
            56)
        global_search_border = page.locator(
            '[data-global-search-input]').evaluate(
                '''element => {
                    const style = getComputedStyle(element);
                    return {
                        top: style.borderTopWidth,
                        right: style.borderRightWidth,
                        bottom: style.borderBottomWidth,
                        left: style.borderLeftWidth,
                        radius: style.borderRadius,
                    };
                }''')
        self.assertEqual(global_search_border['top'], '0px')
        self.assertEqual(global_search_border['right'], '0px')
        self.assertNotEqual(global_search_border['bottom'], '0px')
        self.assertEqual(global_search_border['left'], '0px')
        self.assertEqual(global_search_border['radius'], '0px')
        page.locator('[data-panel-option="menu"]').click()

        page.get_by_role(
            'button', name='Cassini Widget Matrix',
            exact=True).click()
        page.get_by_role(
            'button', name='Cassini Calendar', exact=True).click()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(2)
        page.get_by_role(
            'tab', name='Cassini Widget Matrix', exact=True).click()
        expect(page.locator('.vs-row-current')).to_have_count(0)
        expect(page.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(0)
        expect(page.get_by_role(
            'button', name='Hidden Mark', exact=True)).to_have_count(0)
        alpha_relation = page.locator(
            '.vs-row', has=page.get_by_text(
                'Widget Alpha', exact=True)).get_by_role(
                    'link', name='Widget Group One', exact=True)
        expect(alpha_relation).to_be_visible()
        alpha_row = page.locator(
            '.vs-row', has=page.get_by_text('Widget Alpha', exact=True))
        expect(alpha_row.get_by_text(
            self.today.strftime('%d/%m/%Y'), exact=True)).to_be_visible()
        expect(alpha_row.get_by_text(
            self.now.strftime('%H:%M:%S'), exact=True)).to_be_visible()
        tree_binary = alpha_row.locator('.vs-tree-binary')
        expect(tree_binary.get_by_text('6B', exact=True)).to_be_visible()
        expect(tree_binary.get_by_role(
            'link', name='Save as', exact=True)).to_have_attribute(
                'download', 'binary.txt')
        with page.expect_download() as download_info:
            tree_binary.get_by_role(
                'link', name='Save as', exact=True).click()
        self.assertEqual(download_info.value.suggested_filename, 'binary.txt')
        with page.expect_response(
                lambda response: '/relation/res.group/' in response.url):
            alpha_relation.click()
        group_dialog = page.locator('.vs-relation-record-dialog')
        expect(group_dialog).to_be_visible()
        group_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        expect(group_dialog).not_to_be_visible()
        local_search_border = page.locator(
            '.vs-search-toolbar .vs-search-input').evaluate(
                '''element => {
                    const style = getComputedStyle(element);
                    return {
                        top: style.borderTopWidth,
                        right: style.borderRightWidth,
                        bottom: style.borderBottomWidth,
                        left: style.borderLeftWidth,
                        radius: style.borderRadius,
                    };
                }''')
        self.assertEqual(local_search_border['top'], '0px')
        self.assertEqual(local_search_border['right'], '0px')
        self.assertNotEqual(local_search_border['bottom'], '0px')
        self.assertEqual(local_search_border['left'], '0px')
        self.assertEqual(local_search_border['radius'], '0px')
        header_tabs = page.locator('#workspace-tabs')
        tab_box = header_tabs.locator('.vs-tab').last.bounding_box()
        tabs_box = header_tabs.bounding_box()
        self.assertLessEqual(
            abs(
                tab_box['x'] + tab_box['width']
                - tabs_box['x'] - tabs_box['width']),
            2)
        window_menu = page.locator('details.vs-window-menu')
        window_menu.locator('.vs-window-title').click()
        window_action = window_menu.get_by_role(
            'menuitem', name='Action', exact=True)
        expect(window_action).to_be_visible()
        window_action_layout = window_action.evaluate(
            '''element => {
                const icon = element.querySelector('.vs-icon');
                const text = element.querySelector('span');
                const iconBox = icon.getBoundingClientRect();
                const textBox = text.getBoundingClientRect();
                return {
                    display: getComputedStyle(element).display,
                    iconCenter: iconBox.top + iconBox.height / 2,
                    iconLeft: iconBox.left,
                    textCenter: textBox.top + textBox.height / 2,
                    textLeft: textBox.left,
                };
            }''')
        self.assertEqual(window_action_layout['display'], 'flex')
        self.assertLess(
            window_action_layout['iconLeft'],
            window_action_layout['textLeft'])
        self.assertLessEqual(abs(
            window_action_layout['iconCenter']
            - window_action_layout['textCenter']), 1)
        expect(window_menu.get_by_role(
            'menuitem', name='Mark', exact=True)).to_have_count(0)
        expect(window_menu.get_by_role(
            'menuitem', name='Mark selected',
            exact=True)).to_have_count(0)
        action_popup = page.locator(
            'details.vs-action-popup',
            has=page.locator('summary[aria-label="Action"]'))
        window_menu.get_by_role(
            'menuitem', name='Action', exact=True).click()
        expect(action_popup).to_have_attribute('open', '')
        expect(action_popup.get_by_role(
            'menuitem', name='Mark', exact=True)).to_be_visible()
        expect(action_popup.get_by_role(
            'menuitem', name='Mark selected', exact=True)).to_be_visible()
        beta_row = page.locator(
            '.vs-row', has=page.get_by_text('Widget Beta', exact=True))
        expect(beta_row.get_by_role(
            'button', name='Mark', exact=True).locator(
                'img[src$="tryton-ok.svg"]')).to_be_visible()
        beta_row.get_by_role('button', name='Mark', exact=True).click()
        expect(beta_row.get_by_text('Marked', exact=True)).to_be_visible()
        expect(alpha_row.get_by_text('Draft', exact=True)).to_be_visible()
        alpha_row.get_by_role(
            'checkbox', name='Select record').check()
        multiple_actions = page.locator('.vs-tree-multiple-actions')
        expect(multiple_actions).to_be_visible()
        expect(multiple_actions.get_by_role(
            'button', name='Mark selected', exact=True)).to_be_visible()
        action_width = page.wait_for_function(
            '''() => {
                const element = document.querySelector(
                    ".vs-tree-multiple-actions");
                return element?.getBoundingClientRect().width || false;
            }''').json_value()
        table_width = page.wait_for_function(
            '''() => {
                const element = document.querySelector(".vs-table");
                return element?.getBoundingClientRect().width || false;
            }''').json_value()
        self.assertGreater(action_width, table_width * .8)
        multiple_actions.get_by_role(
            'button', name='Mark selected', exact=True).click()
        expect(alpha_row.get_by_text('Marked', exact=True)).to_be_visible()

        page.locator('[aria-label="Columns"]').click()
        integer_column = page.locator(
            '.vs-column-option',
            has_text='Integer').get_by_role('checkbox')
        integer_column.check()
        expect(page.get_by_role(
                'button', name='Integer', exact=True)).to_be_visible()
        expect(page.locator(
            '.vs-tree-affix', has_text='units').first).to_be_visible()
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_role(
                'button', name='Integer', exact=True)).to_be_visible()

        beta_row.get_by_text('Widget Beta', exact=True).click()
        expect(beta_row.get_by_role(
                'checkbox', name='Select record')).to_be_checked()
        beta_row.get_by_text('Widget Beta', exact=True).dblclick()
        expect(page.locator('.vs-form')).to_be_visible()
        switch = page.get_by_label('Switch view')
        expect(switch).to_have_attribute('data-next-view', 'tree')
        switch.click()
        expect(page.locator(
            '.vs-screen > .vs-table-wrap > .vs-table')).to_be_visible()
        expect(page.locator(
            '.vs-table .vs-hierarchy-toggle-placeholder')).to_have_count(0)
        expect(page.locator('.vs-view-switcher')).to_have_count(0)
        switch = page.get_by_label('Switch view')
        expect(switch).to_have_attribute('data-next-view', 'form')
        switch.click()
        expect(page.locator('.vs-search-toolbar')).to_have_count(0)
        expect(page.locator(
            '[data-field="char_value"] input')).to_be_focused()
        widget_names = {
            'binary', 'boolean', 'callto', 'char', 'color', 'date',
            'datetime', 'dict', 'document', 'email', 'float', 'html',
            'image', 'integer', 'many2many', 'many2one', 'multiselection',
            'numeric', 'one2many', 'one2one', 'password', 'progressbar',
            'pyson', 'reference', 'richtext', 'selection', 'sip', 'text',
            'time', 'timedelta', 'timestamp', 'url',
            }
        for widget_name in widget_names:
            expect(page.locator(
                    f'[data-widget="{widget_name}"]')).to_be_visible()
        binary = page.locator('[data-field="binary_value"]')
        expect(binary.locator('[data-binary-filename]')).to_have_value(
            'beta.txt')
        expect(binary.locator('[data-binary-size]')).to_have_value('4B')
        expect(binary.get_by_role(
            'link', name='Save as', exact=True)).to_have_attribute(
                'download', 'beta.txt')
        expect(binary.get_by_role(
            'button', name='Clear', exact=True)).to_be_visible()
        expect(binary.locator('[data-binary-select]')).to_be_hidden()
        filename = binary.locator('[data-binary-filename]')
        with page.expect_response(
                lambda response: '/field/binary_filename' in response.url):
            filename.fill('renamed.txt')
            filename.blur()
        expect(binary.locator('[data-binary-filename]')).to_have_value(
            'renamed.txt')
        expect(binary.get_by_role(
            'link', name='Save as', exact=True)).to_have_attribute(
                'download', 'renamed.txt')
        with page.expect_response(
                lambda response: '/field/binary_value' in response.url):
            binary.get_by_role('button', name='Clear', exact=True).click()
        expect(binary.locator('[data-binary-filename]')).to_have_value('')
        expect(binary.locator('[data-binary-size]')).to_have_value('')
        expect(binary.get_by_role(
            'link', name='Save as', exact=True)).to_have_count(0)
        expect(binary.get_by_role(
            'button', name='Clear', exact=True)).to_have_count(0)
        expect(binary.locator('[data-binary-select]')).to_be_visible()
        with page.expect_response(
                lambda response: '/field/binary_value' in response.url):
            binary.locator('input[type="file"]').set_input_files({
                'name': 'updated.txt',
                'mimeType': 'text/plain',
                'buffer': b'Updated binary',
                })
        expect(binary.locator('[data-binary-filename]')).to_have_value(
            'updated.txt')
        expect(binary.locator('[data-binary-size]')).to_have_value('14B')
        expect(binary.get_by_role(
            'link', name='Save as', exact=True)).to_have_attribute(
                'download', 'updated.txt')
        expect(binary.get_by_role(
            'button', name='Clear', exact=True)).to_be_visible()
        reference = page.locator('[data-field="reference_value"]')
        expect(reference.locator('[data-reference-model]')).to_have_value(
            'res.group')
        expect(reference.locator('[data-reference-input]')).to_have_value(
            'Widget Group One')
        form_link = page.locator(
            '.vs-link-button', has_text='Cassini Widget Link')
        expect(form_link).to_be_visible()
        link_content = form_link.evaluate(
            '''element => {
                element.style.height = '80px';
                const icon = element.querySelector('.vs-icon');
                const label = element.querySelector('.vs-link-label');
                const box = element.getBoundingClientRect();
                const iconBox = icon.getBoundingClientRect();
                const labelBox = label.getBoundingClientRect();
                return {
                    buttonCenter: box.top + box.height / 2,
                    contentCenter: (
                        Math.min(iconBox.top, labelBox.top)
                        + Math.max(iconBox.bottom, labelBox.bottom)) / 2,
                    justifyContent: getComputedStyle(element).justifyContent,
                };
            }''')
        self.assertEqual(link_content['justifyContent'], 'center')
        self.assertLessEqual(abs(
            link_content['buttonCenter']
            - link_content['contentCenter']), 1)
        date_input = page.locator(
            '[data-field="date_value"] [data-temporal-input]')
        expect(date_input).to_have_attribute('type', 'text')
        expect(date_input).to_have_attribute(
            'data-temporal-format', '%d/%m/%Y')
        with page.expect_response(
                lambda response: '/field/date_value' in response.url):
            date_input.fill('0101')
            date_input.blur()
        expect(date_input).to_have_value('01/01/%s' % date.today().year)
        expect(date_input).to_have_attribute(
            'data-temporal-value', '%s-01-01' % date.today().year)
        with page.expect_response(
                lambda response: '/field/date_value' in response.url):
            date_input.press('d')
        expect(date_input).to_have_value('02/01/%s' % date.today().year)
        expect(date_input).to_have_attribute(
            'data-temporal-value',
            date(date.today().year, 1, 2).isoformat())
        with page.expect_response(
                lambda response: '/field/date_value' in response.url):
            date_input.press('=')
        browser_today = page.evaluate(
            '''() => {
                const value = new Date();
                const pad = number => String(number).padStart(2, "0");
                return [value.getFullYear(), pad(value.getMonth() + 1),
                    pad(value.getDate())].join("-");
            }''')
        expect(date_input).to_have_attribute(
            'data-temporal-value', browser_today)
        time_input = page.locator(
            '[data-field="time_value"] [data-temporal-input]')
        expect(time_input).to_have_attribute('type', 'text')
        with page.expect_response(
                lambda response: '/field/time_value' in response.url):
            time_input.press('h')
        expect(time_input).to_have_attribute(
            'data-temporal-value', '11:30:00')
        character_label = page.locator(
            'label.vs-standalone-label', has_text='Character')
        expect(character_label).to_have_count(1)
        expect(character_label).to_have_class(
            'vs-standalone-label vs-label-required')
        expect(character_label).to_have_css('font-size', '14px')
        expect(page.locator(
            '[data-field="char_value"] > .vs-label')).to_have_count(0)
        email_label = page.locator(
            'label.vs-standalone-label', has_text='Email')
        expect(email_label).to_have_count(1)
        self.assertNotIn(
            'vs-label-required',
            email_label.get_attribute('class').split())
        expect(page.locator('.vs-required')).to_have_count(0)
        expect(page.locator(
                'label.vs-standalone-label', has_text='Date')).to_have_count(0)
        unlimited = page.locator(
            '[data-field="callto_value"]').locator(
                'xpath=ancestor::fieldset[1]')
        expect(unlimited.locator(
            ':scope > label.vs-standalone-label')).to_have_count(2)
        self.assertEqual(
            unlimited.evaluate(
                '''element => getComputedStyle(
                    element).gridTemplateColumns.split(" ").length'''),
            4)
        self.assertEqual(
            unlimited.evaluate(
                'element => getComputedStyle(element).borderTopWidth'),
            '0px')
        unlimited_centers = unlimited.locator(
            ':scope > label.vs-standalone-label, '
            ':scope > .vs-field').evaluate_all(
                '''elements => elements.map(element => {
                    const box = element.getBoundingClientRect();
                    return box.top + box.height / 2;
                })''')
        self.assertLessEqual(
            max(unlimited_centers) - min(unlimited_centers), 2)
        expect(page.locator(
            '.vs-separator-label', has_text='Email')).to_have_count(1)
        notebook = page.locator('.vs-notebook')
        notebook_tab = notebook.get_by_role(
            'tab', name='Character', exact=True)
        expect(notebook_tab).to_be_visible()
        expect(notebook_tab).to_have_attribute('aria-selected', 'true')
        expect(notebook.locator(
            '.vs-notebook-tabs')).to_have_css('overflow-y', 'hidden')
        expect(notebook.get_by_role(
            'tabpanel')).to_have_attribute(
                'aria-labelledby', notebook_tab.get_attribute('id'))
        notebook_geometry = notebook.evaluate(
            '''element => {
                const nav = element.querySelector('.vs-notebook-tabs');
                const active = nav.querySelector(
                    '.vs-local-tab-active');
                const list = nav.querySelector('.vs-tab-list');
                const page = element.querySelector('.vs-page');
                const navBox = nav.getBoundingClientRect();
                const activeBox = active.getBoundingClientRect();
                const pageBox = page.getBoundingClientRect();
                const navStyle = getComputedStyle(nav);
                const navLineStyle = getComputedStyle(nav, '::after');
                const activeStyle = getComputedStyle(active);
                const listStyle = getComputedStyle(list);
                const pageStyle = getComputedStyle(page);
                return {
                    activeBottom: activeBox.bottom,
                    activeBackground: activeStyle.backgroundColor,
                    activeBorderBottom: activeStyle.borderBottomWidth,
                    activeBorderLeft: activeStyle.borderLeftWidth,
                    listZIndex: listStyle.zIndex,
                    navBottom: navBox.bottom,
                    navBorderBottom: navStyle.borderBottomWidth,
                    navLineBackground: navLineStyle.backgroundColor,
                    navLineHeight: navLineStyle.height,
                    pageTop: pageBox.top,
                    pageBackground: pageStyle.backgroundColor,
                    pageBorderLeft: pageStyle.borderLeftWidth,
                };
            }''')
        self.assertLessEqual(abs(
            notebook_geometry['activeBottom']
            - notebook_geometry['navBottom']), 1)
        self.assertLessEqual(abs(
            notebook_geometry['pageTop']
            - notebook_geometry['navBottom']), 1)
        self.assertEqual(notebook_geometry['activeBorderBottom'], '0px')
        self.assertEqual(notebook_geometry['activeBorderLeft'], '1px')
        self.assertEqual(
            notebook_geometry['activeBackground'],
            notebook_geometry['pageBackground'])
        self.assertEqual(notebook_geometry['listZIndex'], '1')
        self.assertEqual(notebook_geometry['navBorderBottom'], '0px')
        self.assertEqual(notebook_geometry['navLineHeight'], '1px')
        self.assertNotEqual(
            notebook_geometry['navLineBackground'],
            'rgba(0, 0, 0, 0)')
        self.assertEqual(notebook_geometry['pageBorderLeft'], '1px')
        expect(page.locator(
            '.vs-page .vs-separator-label',
            has_text='Boolean')).to_have_count(1)
        form_columns = page.locator('.vs-form').get_attribute('style')
        self.assertIn('minmax(0, 1fr)', form_columns)
        self.assertGreater(
            page.locator(
                '[data-field="char_value"]').bounding_box()['width'],
            character_label.bounding_box()['width'])
        character_input = page.locator(
            '[data-field="char_value"] input')
        character_input_style = character_input.evaluate(
            '''element => {
                const style = getComputedStyle(element);
                const box = element.getBoundingClientRect();
                return {
                    borderBottom: style.borderBottomWidth,
                    borderLeft: style.borderLeftWidth,
                    borderRight: style.borderRightWidth,
                    borderTop: style.borderTopWidth,
                    height: box.height,
                };
            }''')
        self.assertEqual(character_input_style['borderBottom'], '1px')
        self.assertEqual(character_input_style['borderLeft'], '0px')
        self.assertEqual(character_input_style['borderRight'], '0px')
        self.assertEqual(character_input_style['borderTop'], '0px')
        self.assertLessEqual(character_input_style['height'], 32)
        character_centers = page.locator(
            'label.vs-standalone-label[for$="char_value-input"], '
            '[data-field="char_value"] input').evaluate_all(
                '''elements => elements.map(element => {
                    const box = element.getBoundingClientRect();
                    return box.top + box.height / 2;
                })''')
        self.assertLessEqual(
            max(character_centers) - min(character_centers), 2)
        boolean_box = page.locator(
            '[data-field="boolean_value"] '
            'input[type="checkbox"]').bounding_box()
        self.assertLessEqual(boolean_box['width'], 20)
        self.assertLessEqual(boolean_box['height'], 20)
        form_button = page.get_by_role(
            'button', name='Change Character', exact=True)
        expect(form_button.locator(
            'img[src$="tryton-ok.svg"]')).to_be_visible()
        self.assertGreater(
            form_button.bounding_box()['width'],
            form_button.locator('span').bounding_box()['width'] + 40)
        text_input = page.locator('[data-field="text_value"] textarea')
        text_input_handle = text_input.element_handle()
        with page.expect_response(
                lambda response: '/field/text_value' in response.url):
            text_input.fill('Text draft without replacing the input')
        self.assertTrue(text_input_handle.evaluate(
            'element => element.isConnected'))
        expect(text_input).to_be_focused()
        expect(text_input).to_have_value(
            'Text draft without replacing the input')

        one2many = page.locator('[data-field="one2many_value"]')
        expect(one2many.locator('.vs-x2many-panel')).to_be_visible()
        expect(one2many.locator(
            '.vs-x2many-string')).to_have_text('One to Many')
        relation_actions = one2many.get_by_role(
            'toolbar', name='Relation actions')
        for action in (
                'Switch', 'Previous', 'Next', 'New', 'Open',
                'Delete', 'Undelete'):
            expect(relation_actions.get_by_role(
                    'button', name=action, exact=True)).to_be_visible()
        expect(one2many.get_by_text(
                'Beta Child One', exact=True)).to_be_visible()
        expect(one2many.locator(
            '.vs-x2many-badge')).to_have_text('1 / 2')
        expect(one2many.locator(
            'summary[aria-label="Columns"]')).to_be_visible()
        one2many_add_input = one2many.locator(
            '[data-x2many-add-input]')
        expect(one2many_add_input).to_be_editable()
        one2many_add_input.fill('Typed Child Search')
        one2many_add_input.press('F2')
        relation_search = page.get_by_role(
            'dialog', name='Search One to Many')
        expect(relation_search).to_be_visible()
        expect(relation_search.locator(
            'input[name="query"]')).to_have_value('Typed Child Search')
        page.get_by_role('button', name='Cancel', exact=True).click()
        one2many_add_input.fill('Typed Child Creation')
        one2many_add_input.press('F3')
        child_dialog = page.locator('.vs-relation-record-dialog')
        expect(child_dialog).to_be_visible()
        expect(child_dialog.locator(
            '[data-field="name"] input')).to_have_value(
                'Typed Child Creation')
        child_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        page.get_by_role(
            'alertdialog', name='Unsaved changes').get_by_role(
                'button', name='Close without saving', exact=True).click()
        expect(child_dialog).not_to_be_visible()
        relation_actions.get_by_role(
            'button', name='Switch', exact=True).click()
        expect(one2many.locator('.vs-x2many-form')).to_be_visible()
        expect(one2many.locator(
            '[data-field="name"] input')).to_have_value('Beta Child One')
        relation_actions.get_by_role(
            'button', name='Switch', exact=True).click()

        one2many = page.locator('[data-field="one2many_value"]')
        one2many.locator('.vs-row').first.dblclick()
        child_dialog = page.locator('.vs-relation-record-dialog')
        expect(child_dialog).to_be_visible()
        expect(child_dialog.locator('.vs-toolbar')).to_have_count(0)
        expect(child_dialog.get_by_role(
            'button', name='Save', exact=True)).to_have_count(0)
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(2)
        expect(child_dialog.locator(
            '[data-field="name"] input')).to_have_value('Beta Child One')
        navigation = child_dialog.get_by_role(
            'group', name='Relation actions', exact=True)
        expect(navigation).to_contain_text('1 / 2')
        expect(navigation.get_by_role(
            'button', name='Previous', exact=True)).to_be_disabled()
        expect(navigation.get_by_role(
            'button', name='Next', exact=True)).to_be_enabled()
        navigation.get_by_role(
            'button', name='Next', exact=True).click()
        child_dialog = page.locator('.vs-relation-record-dialog')
        expect(child_dialog.locator(
            '[data-field="name"] input')).to_have_value('Beta Child Two')
        navigation = child_dialog.get_by_role(
            'group', name='Relation actions', exact=True)
        expect(navigation).to_contain_text('2 / 2')
        expect(navigation.get_by_role(
            'button', name='Previous', exact=True)).to_be_enabled()
        expect(navigation.get_by_role(
            'button', name='Next', exact=True)).to_be_disabled()
        navigation.get_by_role(
            'button', name='Previous', exact=True).click()
        child_dialog = page.locator('.vs-relation-record-dialog')
        expect(child_dialog.locator(
            '[data-field="name"] input')).to_have_value('Beta Child One')
        child_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        expect(child_dialog).not_to_be_visible()
        expect(page.locator(
            '#workspace-tabs .vs-tab-active .vs-tab-title')).to_contain_text(
                'Cassini Widget Matrix')
        page.get_by_role(
            'button', name='Close Cassini Calendar', exact=True).click()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)

        one2many = page.locator('[data-field="one2many_value"]')
        relation_actions = one2many.get_by_role(
            'toolbar', name='Relation actions')
        relation_actions.get_by_role(
            'button', name='New', exact=True).click()
        child_dialog = page.locator('.vs-relation-record-dialog')
        expect(child_dialog).to_be_visible()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)
        child_name = child_dialog.locator('[data-field="name"] input')
        expect(child_dialog.locator(
            '.vs-form input:focus, .vs-form select:focus, '
            '.vs-form textarea:focus')).to_have_count(1)
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            child_name.fill('Created Child in Popup')
        with page.expect_response(
                lambda response: response.url.endswith('/records/save')):
            child_dialog.get_by_role(
                'button', name='OK', exact=True).click()
        expect(child_dialog).not_to_be_visible()
        expect(page.locator(
            '[data-field="one2many_value"]')).to_contain_text(
                'Created Child in Popup')

        one2many = page.locator('[data-field="one2many_value"]')
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            one2many.get_by_text(
                'Beta Child One', exact=True).click()
        one2many = page.locator('[data-field="one2many_value"]')
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            one2many.get_by_text(
                'Beta Child Two', exact=True).click(modifiers=['Control'])
        one2many = page.locator('[data-field="one2many_value"]')
        expect(one2many.locator('.vs-row-selected')).to_have_count(2)
        relation_actions = one2many.get_by_role(
            'toolbar', name='Relation actions')
        relation_actions.get_by_role(
            'button', name='Delete', exact=True).click()
        one2many = page.locator('[data-field="one2many_value"]')
        deleted_rows = one2many.locator('.vs-x2many-row-deleted')
        expect(deleted_rows).to_have_count(2)
        expect(deleted_rows).to_contain_text([
                'Beta Child One', 'Beta Child Two'])
        relation_actions = one2many.get_by_role(
            'toolbar', name='Relation actions')
        expect(relation_actions.get_by_role(
                'button', name='Undelete', exact=True)).to_be_enabled()
        relation_actions.get_by_role(
            'button', name='Undelete', exact=True).click()
        one2many = page.locator('[data-field="one2many_value"]')
        one2many.get_by_role(
            'button', name='Undelete', exact=True).click()
        expect(one2many.locator(
                '.vs-x2many-row-deleted')).to_have_count(0)
        expect(one2many.get_by_text(
                'Beta Child One', exact=True)).to_be_visible()
        many2many = page.locator('[data-field="many2many_value"]')
        expect(many2many.locator(
            '.vs-many2many-panel')).to_be_visible()
        many2many_actions = many2many.get_by_role(
            'toolbar', name='Relation actions')
        expect(many2many.locator(
            '[data-many2many-input]')).to_be_editable()
        expect(many2many.locator(
            'summary[aria-label="Columns"]')).to_be_visible()
        for action in ('Add', 'Remove', 'Undelete'):
            expect(many2many_actions.get_by_role(
                'button', name=action, exact=True)).to_be_visible()
        for one2many_action in (
                'Switch', 'Previous', 'Next', 'New', 'Open', 'Delete'):
            expect(many2many_actions.get_by_role(
                'button', name=one2many_action,
                exact=True)).to_have_count(0)
        many2many_input = many2many.locator(
            '[data-many2many-input]')
        many2many_input.fill('Typed Many to Many Search')
        many2many_input.press('F2')
        relation_search = page.get_by_role(
            'dialog', name='Search Many to Many')
        expect(relation_search).to_be_visible()
        expect(relation_search.locator(
            'input[name="query"]')).to_have_value(
                'Typed Many to Many Search')
        page.get_by_role('button', name='Cancel', exact=True).click()
        many2many_input.fill('Typed Many to Many Creation')
        many2many_input.press('F3')
        relation_record_dialog = page.locator(
            '.vs-relation-record-dialog')
        expect(relation_record_dialog).to_be_visible()
        expect(relation_record_dialog.locator(
            '[data-field="name"] input')).to_have_value(
                'Typed Many to Many Creation')
        relation_record_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        page.get_by_role(
            'alertdialog', name='Unsaved changes').get_by_role(
                'button', name='Close without saving', exact=True).click()
        expect(relation_record_dialog).not_to_be_visible()
        many2many = page.locator('[data-field="many2many_value"]')
        many2many_input = many2many.locator('[data-many2many-input]')
        with page.expect_response(
                lambda response: response.url.endswith('/autocomplete')):
            many2many_input.fill('Widget Group Two')
        many2many_option = many2many.locator(
            '.vs-relation-option', has_text='Widget Group Two')
        expect(many2many_option).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/add')):
            many2many_option.click()
        many2many = page.locator('[data-field="many2many_value"]')
        expect(many2many.get_by_text(
            'Widget Group Two', exact=True)).to_be_visible()
        many2many_input = many2many.locator('[data-many2many-input]')
        with page.expect_response(
                lambda response: response.url.endswith('/autocomplete')):
            many2many_input.fill('Widget Group One')
        many2many_option = many2many.locator(
            '.vs-relation-option', has_text='Widget Group One')
        expect(many2many_option).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/add')):
            many2many_option.click()
        many2many = page.locator('[data-field="many2many_value"]')
        expect(many2many.get_by_text(
            'Widget Group One', exact=True)).to_be_visible()
        many2many_actions = many2many.get_by_role(
            'toolbar', name='Relation actions')
        many2many_actions.get_by_role(
            'button', name='Add', exact=True).click()
        expect(page.get_by_role(
            'dialog', name='Search Many to Many')).to_be_visible()
        page.get_by_role('button', name='Cancel', exact=True).click()
        many2many = page.locator('[data-field="many2many_value"]')
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            many2many.get_by_text(
                'Widget Group One', exact=True).click()
        many2many = page.locator('[data-field="many2many_value"]')
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            many2many.get_by_text(
                'Widget Group Two', exact=True).click(
                    modifiers=['Control'])
        many2many = page.locator('[data-field="many2many_value"]')
        expect(many2many.locator('.vs-row-selected')).to_have_count(2)
        many2many_actions = many2many.get_by_role(
            'toolbar', name='Relation actions')
        many2many_actions.get_by_role(
            'button', name='Remove', exact=True).click()
        many2many = page.locator('[data-field="many2many_value"]')
        expect(many2many.locator(
            '.vs-x2many-row-deleted')).to_have_count(2)
        many2many.get_by_role(
            'button', name='Undelete', exact=True).click()
        many2many = page.locator('[data-field="many2many_value"]')
        many2many.get_by_role(
            'button', name='Undelete', exact=True).click()
        expect(page.locator(
            '[data-field="many2many_value"] '
            '.vs-x2many-row-deleted')).to_have_count(0)

        relation = page.locator(
            '[data-field="many2one_value"] [data-relation-input]')
        relation.click()
        expect(page.locator(
            '[data-field="many2one_value"] '
            '.vs-relation-completion')).not_to_be_visible()
        with page.expect_response(
                lambda response: '/many2one_value/autocomplete'
                in response.url):
            relation.fill('Widget Group O')
        completion = page.locator(
            '[data-field="many2one_value"] .vs-relation-completion')
        expect(completion).to_be_visible()
        with page.expect_response(
                lambda response: '/many2one_value/autocomplete'
                in response.url):
            relation.fill('Very Long Widget Group')
        long_option = completion.get_by_role(
            'option',
            name=(
                'Very Long Widget Group Suggestion That Must Stay on One '
                'Line'), exact=True)
        expect(long_option).to_be_visible()
        self.assertEqual(
            long_option.evaluate(
                'element => getComputedStyle(element).whiteSpace'),
            'nowrap')
        self.assertGreater(
            completion.bounding_box()['width'],
            relation.bounding_box()['width'])
        with page.expect_response(
                lambda response: '/many2one_value/autocomplete'
                in response.url):
            relation.fill('Widget Group O')
        expect(page.locator(
            '[data-field="many2one_value"] datalist')).to_have_count(0)
        with page.expect_response(
                lambda response: '/field/many2one_value'
                in response.url and '/autocomplete' not in response.url):
            completion.get_by_role(
                'option', name='Widget Group One', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="many2one_value"] '
                '[data-relation-input]')).to_have_value(
                    'Widget Group One')

        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        expect(relation_widget.get_by_role(
            'button', name='Open the record')).to_be_visible()
        expect(relation_widget.get_by_role(
            'button', name='Clear the field')).to_be_visible()
        relation_widget.get_by_role(
            'button', name='Open the record').click()
        relation_record_dialog = page.locator(
            '.vs-relation-record-dialog')
        expect(relation_record_dialog).to_be_visible()
        expect(relation_record_dialog.locator(
            '[data-field="name"] input')).to_have_value(
                'Widget Group One')
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)
        relation_record_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        expect(relation_record_dialog).not_to_be_visible()

        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        relation_widget.get_by_role(
            'button', name='Open the record').click(
                modifiers=['Control'])
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(2)
        relation_tab = page.locator(
            '#workspace-tabs .vs-tab',
            has_text='Widget Group One')
        expect(relation_tab).to_be_visible()
        relation_tab.locator('.vs-tab-close').click()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)

        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        with page.expect_response(
                lambda response: (
                    '/field/many2one_value' in response.url
                    and '/autocomplete' not in response.url)):
            relation_widget.get_by_role(
                'button', name='Clear the field').click()
        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        relation = relation_widget.locator('[data-relation-input]')
        with page.expect_response(
                lambda response: '/many2one_value/autocomplete'
                in response.url):
            relation.fill('Widget Group Tw')
        completion = relation_widget.locator('.vs-relation-completion')
        completion.get_by_role(
            'button', name='Search…', exact=True).click()
        relation_dialog = page.get_by_role(
            'dialog', name='Search Many to One')
        expect(relation_dialog).to_be_visible()
        expect(relation_dialog.locator(
            'input[name="query"]')).to_have_value('Widget Group Tw')
        expect(relation_dialog.locator(
            '.vs-relation-search-table')).to_be_visible()
        expect(relation_dialog.locator(
            'th', has_text='Name')).to_be_visible()
        group_two_row = relation_dialog.locator(
            '[data-relation-search-row]',
            has_text='Widget Group Two')
        group_two_row.click()
        expect(relation_dialog.get_by_role(
            'button', name='OK', exact=True)).to_be_enabled()
        relation_dialog.get_by_role(
            'button', name='OK', exact=True).click()
        expect(page.locator(
            '[data-field="many2one_value"] '
            '[data-relation-input]')).to_have_value(
                'Widget Group Two')

        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        with page.expect_response(
                lambda response: (
                    '/field/many2one_value' in response.url
                    and '/autocomplete' not in response.url)):
            relation_widget.get_by_role(
                'button', name='Clear the field').click()
        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        expect(relation_widget.locator(
            '[data-relation-input]')).to_have_value('')
        relation_widget.get_by_role(
            'button', name='Search a record').click()
        relation_dialog = page.get_by_role(
            'dialog', name='Search Many to One')
        relation_dialog.locator(
            '[data-relation-search-row]',
            has_text='Widget Group One').dblclick()
        expect(page.locator(
            '[data-field="many2one_value"] '
            '[data-relation-input]')).to_have_value(
                'Widget Group One')

        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        with page.expect_response(
                lambda response: (
                    '/field/many2one_value' in response.url
                    and '/autocomplete' not in response.url)):
            relation_widget.get_by_role(
                'button', name='Clear the field').click()
        relation_widget = page.locator(
            '[data-field="many2one_value"] [data-relation-widget]')
        expect(relation_widget.locator(
            '[data-relation-input]')).to_have_value('')
        relation = relation_widget.locator('[data-relation-input]')
        with page.expect_response(
                lambda response: '/many2one_value/autocomplete'
                in response.url):
            relation.fill('Created from Relation')
        completion = relation_widget.locator('.vs-relation-completion')
        completion.get_by_role(
            'button', name='Create…', exact=True).click()
        relation_record_dialog = page.locator(
            '.vs-relation-record-dialog')
        expect(relation_record_dialog).to_be_visible()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)
        related_name = relation_record_dialog.locator(
            '[data-field="name"] input')
        expect(related_name).to_have_value('Created from Relation')
        expect(relation_record_dialog.locator(
            '.vs-form input:focus, .vs-form select:focus, '
            '.vs-form textarea:focus')).to_have_count(1)
        with page.expect_response(
                lambda response: '/records/save' in response.url):
            relation_record_dialog.get_by_role(
                'button', name='OK', exact=True).click()
        expect(relation_record_dialog).not_to_be_visible()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(1)
        expect(page.locator(
                '[data-field="many2one_value"] '
                '[data-relation-input]')).to_have_value(
                    'Created from Relation')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="many2one_value"] '
                '[data-relation-input]')).to_have_value(
                    'Created from Relation')

        page.get_by_role(
            'button', name='Change Character', exact=True).click()
        expect(page.locator(
                '[data-field="char_value"] input')).to_have_value(
                    'Instance Widget Beta')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="char_value"] input')).to_have_value(
                    'Instance Widget Beta')

        page.get_by_role(
            'button', name='Cassini List Form',
            exact=True).click()
        expect(page.locator('.vs-list-form .vs-card')).to_have_count(2)
        beta_card = page.locator(
            '.vs-card', has=page.locator(
                'input[value="Widget Beta"]'))
        beta_name = beta_card.locator('[data-field="char_value"] input')
        beta_name.press('Control+A')
        with page.expect_response(
                lambda response: '/field/char_value' in response.url):
            beta_name.press_sequentially('List Form Draft')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
            'input[value="List Form Draft"]')).to_be_visible()
        with page.expect_response(
                lambda response:
                response.url.endswith('/records/save')):
            page.get_by_role(
                'button', name='Save', exact=True).click()
        page.locator('.vs-window-title').click()
        page.get_by_role(
            'menuitem', name='Revisions', exact=True).click()
        expect(page.get_by_role(
                'dialog', name='Revisions')).to_be_visible()
        expect(page.locator(
                '.vs-revision-list li').first).to_be_visible()
        page.get_by_role('button', name='Close', exact=True).click()
        expect(page.get_by_role(
                'dialog', name='Revisions')).not_to_be_visible()

        page.get_by_role(
            'button', name='Cassini Calendar',
            exact=True).click()
        expect(page.locator('.vs-calendar')).to_be_visible()
        expect(page.locator('.vs-calendar-event')).to_have_count(2)
        with page.expect_response(
                lambda response: '/calendar/day/'
                in response.url and response.url.endswith('/new')):
            page.get_by_role(
                'button',
                name='New event on ' + date.today().isoformat()).click()
        expect(page.locator('.vs-calendar-event')).to_have_count(3)
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-calendar-event')).to_have_count(3)
        page.get_by_role(
            'navigation', name='Calendar mode').get_by_role(
                'button', name='Week', exact=True).click()
        expect(page.locator('.vs-calendar-week')).to_be_visible()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-calendar-week')).to_be_visible()
        with page.expect_response(
                lambda response: '/calendar/mode/month'
                in response.url):
            page.get_by_role(
                'navigation', name='Calendar mode').get_by_role(
                    'button', name='Month', exact=True).click()
        initial_month = page.locator('.vs-calendar-header h2').text_content()
        with page.expect_response(
                lambda response: '/calendar/next'
                in response.url):
            page.get_by_role('button', name='Next', exact=True).click()
        expect(page.locator(
                '.vs-calendar-header h2')).not_to_have_text(initial_month)
        next_month = page.locator('.vs-calendar-header h2').text_content()
        self.assertNotEqual(next_month, initial_month)
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '.vs-calendar-header h2')).to_have_text(next_month)

        page.get_by_role(
            'button', name='Cassini Scan Code',
            exact=True).click()
        code = page.get_by_role('textbox', name='Code')
        code.fill('Scanned Character')
        with page.expect_response(
                lambda response: response.url.endswith('/scan')):
            page.get_by_role(
                'button', name='Scan', exact=True).click()
        active_char = page.locator(
            '.vs-active-panel > .vs-screen '
            '[data-field="char_value"] input')
        expect(active_char).to_have_value(
                    'Scanned Character')
        page.reload(wait_until='domcontentloaded')
        expect(active_char).to_have_value('Scanned Character')

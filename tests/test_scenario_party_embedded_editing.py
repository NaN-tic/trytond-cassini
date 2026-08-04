from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.pyson import PYSONEncoder
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestPartyEmbeddedEditing(WebTestCase):
    modules = ['cassini', 'party']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Category = pool.get('party.category')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Party = pool.get('party.party')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            categories = Category.create([
                    {'name': 'Cassini Category Assigned'},
                    {'name': 'Cassini Category Keyboard One'},
                    {'name': 'Cassini Category Keyboard Two'},
                    ])
            party, = Party.create([{
                        'name': 'Cassini Editable Party',
                        'addresses': [('create', [{
                                            'party_name': 'Embedded Address',
                                            }])],
                        'categories': [('add', [categories[0].id])],
                        'contact_mechanisms': [('create', [{
                                            'type': 'email',
                                            'value': 'party@example.test',
                                            }])],
                        }])
            view = View(ModelData.get_id('party', 'party_view_form'))
            action, = ActionWindow.create([{
                        'name': 'Cassini Party Embedded Editing',
                        'res_model': 'party.party',
                        'domain': PYSONEncoder().encode([
                                ('id', '=', party.id)]),
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Party Embedded Editing',
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
            'button', name='Cassini Party Embedded Editing',
            exact=True).click()

        addresses = page.locator('[data-field="addresses"]')
        address_name = addresses.locator(
            '.vs-x2many-form [data-field="party_name"] input')
        expect(address_name).to_be_editable()
        with page.expect_response(
                lambda response: '/x2many/' in response.url
                and response.url.endswith('/field/party_name')):
            address_name.fill('Edited Embedded Address')
        expect(address_name).to_have_value('Edited Embedded Address')

        street_name = addresses.locator(
            '.vs-x2many-form [data-field="street_name"]')
        expect(street_name).to_be_visible()
        building_name = addresses.locator(
            '.vs-x2many-form [data-field="building_name"]')
        with page.expect_response(
                lambda response: '/x2many/' in response.url
                and response.url.endswith('/field/building_name')):
            building_name.locator('input').fill('Main Building')
            building_name.locator('input').blur()
        street = addresses.locator(
            '.vs-x2many-form [data-field="street"] textarea')
        with page.expect_response(
                lambda response: '/x2many/' in response.url
                and response.url.endswith('/field/street')):
            street.fill('Main Street')
            street.blur()
        expect(street_name).to_be_hidden()
        expect(building_name).to_be_visible()
        with page.expect_response(
                lambda response: '/x2many/' in response.url
                and response.url.endswith('/field/building_name')):
            building_name.locator('input').fill('')
            building_name.locator('input').blur()
        expect(building_name).to_be_hidden()

        contacts = page.locator('[data-field="contact_mechanisms"]')
        expect(contacts.locator(
            'col[data-column-field="party"]')).to_have_count(0)
        expect(contacts.get_by_role(
            'columnheader', name='Party', exact=True)).to_have_count(0)
        self.assertEqual(
            contacts.locator('.vs-table-wrap').get_attribute(
                'data-editable-tree'),
            'true', contacts.locator('.vs-x2many-table').evaluate(
                'table => table.outerHTML.slice(0, 500)'))
        contact_rows = contacts.locator('.vs-x2many-row')
        expect(contact_rows).to_have_count(1)
        contact_value = contact_rows.first.locator(
            '[data-field="value"] input')
        expect(contact_value).to_be_editable()
        url_icon = contact_rows.first.locator(
            'a.vs-tree-affix[href^="mailto:"]')
        expect(url_icon).to_have_count(1)
        expect(url_icon.locator('img.vs-icon')).to_have_count(1)
        expect(url_icon).not_to_contain_text('party@example.test')
        contact_value.fill('edited@example.test')
        contacts.get_by_role(
            'button', name='New', exact=True).click()
        expect(page.locator('.vs-relation-record-dialog')).to_have_count(0)
        contacts = page.locator('[data-field="contact_mechanisms"]')
        expect(contacts.locator('.vs-x2many-row')).to_have_count(2)
        inline_contact = contacts.locator('.vs-x2many-row').last
        expect(inline_contact.locator(
            '[data-field="type"] select')).to_be_editable()
        expect(inline_contact.locator(
            '[data-field="type"] select')).to_be_focused()
        expect(inline_contact.locator(
            '[data-field="value"] input')).to_be_editable()
        with page.expect_response(
                lambda response: response.url.endswith('/field/type')):
            inline_contact.locator(
                '[data-field="type"] select').select_option('email')
        page.wait_for_timeout(100)
        contacts = page.locator('[data-field="contact_mechanisms"]')
        inline_contact = contacts.locator('.vs-x2many-row').last
        inline_contact.locator('[data-field="value"] input').fill(
            'second@example.test')
        page.wait_for_timeout(600)

        contacts = page.locator('[data-field="contact_mechanisms"]')
        inline_contact = contacts.locator('.vs-x2many-row').last
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/x2many/new')):
            inline_contact.locator(
                '[data-field="value"] input').press('Enter')
        expect(contacts.locator('.vs-x2many-row')).to_have_count(3)

        contacts = page.locator('[data-field="contact_mechanisms"]')
        new_contact = contacts.locator('.vs-x2many-row').last
        expect(new_contact.locator(
            '[data-field="type"] select')).to_be_focused()
        with page.expect_response(
                lambda response: response.url.endswith('/field/type')):
            new_contact.locator(
                '[data-field="type"] select').select_option('email')
        page.wait_for_timeout(100)
        contacts = page.locator('[data-field="contact_mechanisms"]')
        new_contact = contacts.locator('.vs-x2many-row').last
        new_contact.locator('[data-field="value"] input').fill(
            'third@example.test')
        page.wait_for_timeout(600)

        contacts = page.locator('[data-field="contact_mechanisms"]')
        contact_rows = contacts.locator('.vs-x2many-row')
        expect(contact_rows.locator(
            '[data-tree-drag-handle]')).to_have_count(3)
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            contact_rows.first.locator(
                '[data-field="value"]').click()
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            contact_rows.nth(1).locator(
                '[data-field="value"]').click(modifiers=['Control'])
        expect(contacts.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(2)
        expect(contacts.locator('.vs-row-selected')).to_have_count(2)
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/select')):
            contact_rows.nth(2).locator(
                '[data-field="value"]').click(modifiers=['Shift'])
        expect(contacts.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(2)
        expect(contact_rows.first.locator(
            '.vs-select-column input[aria-label="Select record"]'
            )).not_to_be_checked()
        third_contact = contact_rows.last
        first_contact = contact_rows.first
        with page.expect_response(
                lambda response: response.url.endswith('/x2many/move')):
            third_contact.locator('[data-tree-drag-handle]').drag_to(
                first_contact,
                target_position={'x': 20, 'y': 1})
        contacts = page.locator('[data-field="contact_mechanisms"]')
        expect(contacts.locator(
            '.vs-x2many-row [data-field="value"] input').first
            ).to_have_value('third@example.test')

        categories = page.locator('[data-field="categories"]')
        category_input = categories.locator('[data-x2many-add-input]')
        expect(category_input).to_have_css('background-color', 'rgb(255, 255, 255)')
        category_input.fill('Cassini Category Keyboard')
        options = categories.locator('.vs-relation-option')
        expect(options).to_have_count(2)
        category_input.press('ArrowDown')
        expect(options.first).to_be_focused()
        page.keyboard.press('ArrowDown')
        expect(options.nth(1)).to_be_focused()

        with page.expect_response(
                lambda response: response.url.endswith('/save')):
            page.get_by_role('button', name='Save', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
            '[data-field="addresses"] [data-field="party_name"] input'
            )).to_have_value('Edited Embedded Address')
        contact_values = page.locator(
            '[data-field="contact_mechanisms"] [data-field="value"] input')
        expect(contact_values).to_have_count(3)
        expect(contact_values.nth(0)).to_have_value('third@example.test')
        expect(contact_values.nth(1)).to_have_value('edited@example.test')
        expect(contact_values.nth(2)).to_have_value('second@example.test')

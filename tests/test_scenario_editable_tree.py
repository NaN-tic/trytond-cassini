from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestEditableTree(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            view, = View.create([{
                        'model': 'res.group',
                        'type': 'tree',
                        'data': (
                            '<tree editable="1">'
                            '<field name="name"/>'
                            '<field name="active"/>'
                            '<field name="users"/>'
                            '</tree>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Editable Groups',
                        'res_model': 'res.group',
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
                        'name': 'Editable Groups',
                        'action': str(action),
                        }])
            Group.create([
                    {'name': 'Editable Alpha'},
                    {'name': 'Editable Beta'},
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
                'button', name='Editable Groups', exact=True).click()

        name_sort = page.get_by_role('button', name='Name', exact=True)
        name_header = page.locator(
            '.vs-table th', has=page.get_by_role(
                'button', name='Name', exact=True))
        expect(name_header).not_to_have_attribute('aria-sort', 'ascending')
        expect(name_header.locator('.vs-sort-indicator')).to_have_count(0)
        expect(page.get_by_role(
            'button', name='Users', exact=True)).to_have_count(0)
        expect(page.locator(
            '.vs-column-label .vs-sort-label',
            has_text='Users')).to_be_visible()
        names = page.locator('.vs-row [data-field="name"] input')
        self.assertEqual([
                value for value in names.evaluate_all(
                    'elements => elements.map(element => element.value)')
                if value.startswith('Editable ')
                ], ['Editable Alpha', 'Editable Beta'])

        with page.expect_response(
                lambda response: response.url.endswith('/sort/name')):
            name_sort.click()
        expect(name_header).to_have_attribute('aria-sort', 'ascending')
        expect(name_header.locator('.vs-sort-indicator')).to_have_attribute(
            'src', '/cassini-icons/tryton-arrow-down.svg')
        self.assertEqual([
                value for value in names.evaluate_all(
                    'elements => elements.map(element => element.value)')
                if value.startswith('Editable ')
                ], ['Editable Alpha', 'Editable Beta'])

        with page.expect_response(
                lambda response: response.url.endswith('/sort/name')):
            name_sort.click()
        expect(name_header).to_have_attribute('aria-sort', 'descending')
        expect(name_header.locator('.vs-sort-indicator')).to_have_attribute(
            'src', '/cassini-icons/tryton-arrow-up.svg')
        self.assertEqual([
                value for value in names.evaluate_all(
                    'elements => elements.map(element => element.value)')
                if value.startswith('Editable ')
                ], ['Editable Beta', 'Editable Alpha'])

        with page.expect_response(
                lambda response: response.url.endswith('/sort/name')):
            name_sort.click()
        expect(name_header).not_to_have_attribute('aria-sort', 'ascending')
        expect(name_header.locator('.vs-sort-indicator')).to_have_count(0)
        self.assertEqual([
                value for value in names.evaluate_all(
                    'elements => elements.map(element => element.value)')
                if value.startswith('Editable ')
                ], ['Editable Alpha', 'Editable Beta'])

        alpha = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Editable Alpha"]'))
        beta = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Editable Beta"]'))
        alpha_name = alpha.locator('[data-field="name"] input')
        alpha_name.press('Control+A')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            alpha_name.press_sequentially('Editable Alpha Changed')
        expect(page.get_by_role(
                'button', name='Save', exact=True)).to_be_enabled()
        beta_name = beta.locator('[data-field="name"] input')
        beta_name.press('Control+A')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            beta_name.press_sequentially('Editable Beta Changed')

        rows = page.locator('.vs-table tbody .vs-row')
        row_count = rows.count()
        beta_name.press('Enter')
        expect(rows).to_have_count(row_count + 1)
        new_name = rows.first.locator('[data-field="name"] input')
        expect(new_name).to_be_editable()
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            new_name.press_sequentially('Editable Created with Enter')

        page.get_by_role('button', name='Save', exact=True).click()
        expect(page.get_by_text('Unsaved changes')).not_to_be_visible()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                'input[value="Editable Alpha Changed"]')).to_be_visible()
        expect(page.locator(
                'input[value="Editable Beta Changed"]')).to_be_visible()
        expect(page.locator(
                'input[value="Editable Created with Enter"]')).to_be_visible()

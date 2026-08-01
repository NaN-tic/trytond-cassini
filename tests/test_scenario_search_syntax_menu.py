from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestSearchSyntaxMenu(WebTestCase):
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
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            groups = Group.create([
                    {'name': 'stock'},
                    {'name': 'stock lot'},
                    {'name': 'sale'},
                    ])
            cls.stock_id = groups[0].id
            view, = View.create([{
                        'model': 'res.group',
                        'type': 'tree',
                        'data': '<tree><field name="name"/></tree>',
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Search Syntax',
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
            section, = Menu.create([{
                        'name': (
                            'A deliberately long menu section that must stay '
                            'on one line'),
                        }])
            Menu.create([{
                        'name': 'Cassini Search Syntax',
                        'action': str(action),
                        'parent': section.id,
                        }])
            Group.fields_view_get(view_id=view.id, view_type='tree')
            Group.view_toolbar_get()
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

        section = page.get_by_role(
            'button',
            name='A deliberately long menu section that must stay on one line',
            exact=True)
        hierarchy = section.locator(
            'xpath=ancestor::div[contains(@class, "vs-hierarchy-row")][1]')
        expect(hierarchy.locator(
            ':scope > .vs-hierarchy-content > .vs-tree-content'
            )).to_have_count(1)
        geometry = section.evaluate(
            '''element => ({
                clientHeight: element.clientHeight,
                scrollHeight: element.scrollHeight,
                whiteSpace: getComputedStyle(element).whiteSpace,
            })''')
        self.assertEqual(geometry['whiteSpace'], 'nowrap')
        self.assertLessEqual(
            geometry['scrollHeight'], geometry['clientHeight'] + 1)
        section.click()
        page.get_by_role(
            'button', name='Cassini Search Syntax', exact=True).click()

        search = page.get_by_placeholder('Search', exact=True)
        failed_searches = []
        page.on('response', lambda response: (
                failed_searches.append((response.url, response.status))
                if '/search' in response.url and response.status >= 500
                else None))
        search.fill('N')
        expect(page.locator('.vs-search-completion').get_by_role(
            'option', name='Name:', exact=True)).to_be_visible()

        search.fill('Name: =stock')
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        table = page.locator('.vs-table tbody')
        expect(table.get_by_text('stock', exact=True)).to_be_visible()
        expect(table.get_by_text('stock lot', exact=True)).to_have_count(0)
        expect(table.get_by_text('sale', exact=True)).to_have_count(0)

        search.fill('Name: stock')
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        expect(table.get_by_text('stock', exact=True)).to_be_visible()
        expect(table.get_by_text('stock lot', exact=True)).to_be_visible()
        expect(table.get_by_text('sale', exact=True)).to_have_count(0)

        search.fill('Name: =stock | Name: =sale')
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        expect(table.get_by_text('stock', exact=True)).to_be_visible()
        expect(table.get_by_text('sale', exact=True)).to_be_visible()
        expect(table.get_by_text('stock lot', exact=True)).to_have_count(0)

        search.fill('Name: stock;sale')
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        expect(table.get_by_text('stock', exact=True)).to_be_visible()
        expect(table.get_by_text('sale', exact=True)).to_be_visible()
        expect(table.get_by_text('stock lot', exact=True)).to_have_count(0)

        search.fill('ID: =%d' % self.stock_id)
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        expect(table.get_by_text('stock', exact=True)).to_be_visible()
        expect(table.get_by_text('sale', exact=True)).to_have_count(0)
        expect(table.locator('.vs-row')).to_have_count(1)
        self.assertEqual(failed_searches, [])

from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestTreeLazyLoading(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowDomain = pool.get('ir.action.act_window.domain')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Menu = pool.get('ir.ui.menu')
            Node = pool.get('cassini.test.tree.node')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            Node.create([
                    {
                        'name': 'Lazy record %03d' % index,
                        'sequence': index,
                        'amount': Decimal('10.25'),
                        }
                    for index in range(220)
                    ])
            view, = View.create([{
                        'model': 'cassini.test.tree.node',
                        'type': 'tree',
                        'data': (
                            '<tree><field name="name"/>'
                            '<field name="amount" sum="1"/></tree>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Lazy Tree',
                        'res_model': 'cassini.test.tree.node',
                        'context': '{}',
                        'search_value': '[]',
                        'order': '[["sequence", "ASC"]]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            ActionWindowDomain.create([{
                        'name': 'All records',
                        'domain': '[]',
                        'count': True,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Lazy Tree',
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
            'button', name='Cassini Lazy Tree', exact=True).click()

        rows = page.locator('.vs-active-panel .vs-row')
        expect(rows).to_have_count(100)
        loader = page.locator('.vs-tree-loader')
        expect(loader).to_have_attribute(
            'hx-trigger', 'intersect once root:.vs-main')
        expect(loader).to_have_attribute('hx-target', 'this')
        expect(loader).to_have_attribute(
            'hx-select',
            '.vs-row, .vs-tree-loader, .vs-tree-total-row')
        self.assertTrue(loader.get_attribute('hx-get').endswith(
                '/tab/'
                + page.locator('.vs-screen').get_attribute('data-tab')
                + '/tree/records'))

        tree = page.locator('.vs-active-panel .vs-table-wrap')
        expect(tree.locator(
                'tbody > .vs-tree-loader:last-child')).to_have_count(1)
        domains = page.get_by_role('navigation', name='Domains')
        expect(domains).to_be_visible()
        header = page.locator('.vs-active-panel .vs-table th').first
        total = tree.locator('.vs-tree-total')
        total_row = tree.locator('.vs-tree-total-row')
        main = page.locator('.vs-main')
        expect(total).to_have_text('1,025.00')
        expect(total_row).not_to_contain_text('Total')
        self.assertEqual(total_row.evaluate(
                'element => getComputedStyle(element).position'), 'sticky')
        self.assertEqual(total_row.evaluate(
                'element => getComputedStyle(element).bottom'), '0px')
        self.assertGreaterEqual(int(total.evaluate(
                'element => getComputedStyle(element).fontWeight')), 700)
        self.assertIn(total.evaluate(
                'element => getComputedStyle(element).textAlign'),
            {'end', 'right'})
        self.assertEqual(
            tree.evaluate(
                'element => getComputedStyle(element).overflowY'),
            'visible')
        self.assertEqual(
            header.evaluate(
                'element => getComputedStyle(element).position'),
            'sticky')
        main.evaluate('(element) => { element.scrollTop = 200; }')
        expect(header).to_be_visible()
        expect(total_row).to_be_visible()
        header_box = header.bounding_box()
        domains_box = domains.bounding_box()
        total_box = total_row.bounding_box()
        main_box = main.bounding_box()
        self.assertGreaterEqual(
            header_box['y'], domains_box['y'] + domains_box['height'] - 1)
        self.assertLessEqual(
            header_box['y'], domains_box['y'] + domains_box['height'] + 2)
        self.assertLessEqual(
            abs(
                total_box['y'] + total_box['height']
                - main_box['y'] - main_box['height']),
            2)

        with page.expect_response(
                lambda response: '/tree/records' in response.url) \
                as response_info:
            main.evaluate(
                'element => { element.scrollTop = element.scrollHeight; }')
        response_markup = response_info.value.text()
        self.assertEqual(response_markup.count('<tr class="vs-row'), 100)
        self.assertNotIn('Lazy record 000', response_markup)
        self.assertIn('Lazy record 100', response_markup)
        self.assertIn('Lazy record 199', response_markup)
        expect(rows).to_have_count(200)
        expect(total).to_have_text('2,050.00')

        with page.expect_response(
                lambda response: '/tree/records' in response.url) \
                as response_info:
            main.evaluate(
                'element => { element.scrollTop = element.scrollHeight; }')
        response_markup = response_info.value.text()
        self.assertEqual(response_markup.count('<tr class="vs-row'), 20)
        self.assertNotIn('Lazy record 100', response_markup)
        self.assertIn('Lazy record 200', response_markup)
        self.assertIn('Lazy record 219', response_markup)
        expect(rows).to_have_count(220)
        expect(total).to_have_text('2,255.00')
        expect(page.locator('.vs-tree-loader')).to_have_count(0)

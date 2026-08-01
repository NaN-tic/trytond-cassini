from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestTreeFeatures(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Menu = pool.get('ir.ui.menu')
            Node = pool.get('cassini.test.tree.node')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            parent, _sibling = Node.create([
                    {
                        'name': 'Tree Parent',
                        'sequence': 10,
                        'amount': Decimal('5'),
                        },
                    {
                        'name': 'Tree Sibling',
                        'sequence': 20,
                        'amount': Decimal('3'),
                        },
                    ])
            Node.create([{
                        'name': 'Tree Child',
                        'sequence': 10,
                        'amount': Decimal('2'),
                        'parent': parent.id,
                        }])
            view, = View.create([{
                        'model': 'cassini.test.tree.node',
                        'type': 'tree',
                        'field_childs': 'children',
                        'data': (
                            '<tree editable="1" sequence="sequence" '
                            'tree_state="1" '
                            'visual="&quot;success&quot;">'
                            '<field name="name">'
                            '<prefix id="bullet" string="•"/>'
                            '</field>'
                            '<field name="amount" sum="1"/>'
                            '<field name="sequence" optional="1"/>'
                            '</tree>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Tree Features',
                        'res_model': 'cassini.test.tree.node',
                        'domain': '[["parent", "=", null]]',
                        'context': '{}',
                        'search_value': '[]',
                        'order': '[["sequence", "ASC"]]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Tree Features',
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
            'button', name='Cassini Tree Features',
            exact=True).click()

        rows = page.locator('.vs-row')
        expect(rows).to_have_count(2)
        self.assertIn(
            'vs-visual-success',
            rows.first.get_attribute('class'))
        expect(page.locator(
                'input[value="Tree Child"]')).not_to_be_visible()
        parent = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Parent"]'))
        parent_name = parent.locator('input[value="Tree Parent"]')
        expand = parent.get_by_role(
            'button', name='Expand node')
        name_box = parent_name.bounding_box()
        expand_box = expand.bounding_box()
        self.assertLess(expand_box['x'], name_box['x'])
        self.assertLess(
            abs(
                expand_box['y'] + expand_box['height'] / 2
                - name_box['y'] - name_box['height'] / 2),
            3)
        with page.expect_response(
                lambda response: (
                    '/select?' in response.url
                    and 'row=true' in response.url
                    and 'silent=true' in response.url)):
            parent_name.click()
        expect(parent.get_by_role(
                'checkbox', name='Select record')).to_be_checked()
        page.reload(wait_until='domcontentloaded')
        parent = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Parent"]'))
        expect(parent.get_by_role(
                'checkbox', name='Select record')).to_be_checked()
        expect(parent.get_by_text('•', exact=True)).to_be_visible()
        parent.get_by_role(
            'button', name='Expand node').click()
        expect(rows).to_have_count(3)
        child_name = page.locator('input[value="Tree Child"]')
        expect(child_name).to_be_visible()
        child_row = page.locator(
            '.vs-row', has=child_name)
        child_hierarchy = child_row.locator(
            '.vs-tree-hierarchy.vs-hierarchy-child')
        expect(child_hierarchy).to_have_class(
            'vs-hierarchy-row vs-hierarchy-child vs-tree-hierarchy')
        self.assertIn(
            'linear-gradient',
            child_hierarchy.evaluate(
                'element => getComputedStyle(element).backgroundImage'))
        self.assertGreater(
            child_name.bounding_box()['x'] - parent_name.bounding_box()['x'],
            20)
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                'input[value="Tree Child"]')).to_be_visible()
        expect(page.locator('.vs-tree-total')).to_have_text('10')

        parent = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Parent"]'))
        parent.get_by_role(
            'button', name='Move down').click()
        expect(rows.nth(0).locator(
                'input[value="Tree Sibling"]')).to_be_visible()
        page.get_by_role('button', name='Save', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(rows.nth(0).locator(
                'input[value="Tree Sibling"]')).to_be_visible()

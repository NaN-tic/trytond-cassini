import re
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
            view, flat_view = View.create([
                    {
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
                            '<field name="amount" sum="1">'
                            '<suffix name="amount" string=" €"/>'
                            '</field>'
                            '<field name="sequence" optional="1"/>'
                            '</tree>'),
                        }, {
                        'model': 'cassini.test.tree.node',
                        'type': 'tree',
                        'data': (
                            '<tree sequence="sequence">'
                            '<field name="name"/>'
                            '<field name="sequence"/>'
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
            flat_action, = ActionWindow.create([{
                        'name': 'Cassini Sequence List',
                        'res_model': 'cassini.test.tree.node',
                        'domain': '[["parent", "=", null]]',
                        'context': '{}',
                        'search_value': '[]',
                        'order': '[["sequence", "ASC"]]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': flat_view.id,
                        'act_window': flat_action.id,
                        }])
            Menu.create([
                    {
                        'name': 'Cassini Tree Features',
                        'action': str(action),
                        }, {
                        'name': 'Cassini Sequence List',
                        'action': str(flat_action),
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
        expect(page.locator('.vs-row-current')).to_have_count(0)
        expect(page.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(0)
        self.assertIn(
            'vs-visual-success',
            rows.first.get_attribute('class'))
        success_background = rows.first.evaluate(
            'element => getComputedStyle(element).backgroundColor')
        self.assertNotIn(success_background, {
                'rgba(0, 0, 0, 0)', 'transparent'})
        rows.first.hover()
        self.assertNotEqual(
            rows.first.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            success_background)
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
                    and 'row=true' in response.url)):
            parent_name.click()
        expect(parent.get_by_role(
                'checkbox', name='Select record')).to_be_checked()
        sibling = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Sibling"]'))
        sibling_name = sibling.locator('input[value="Tree Sibling"]')
        with page.expect_response(
                lambda response: (
                    '/select?' in response.url
                    and 'row=true' in response.url)):
            sibling_name.click(modifiers=['Control'])
        expect(page.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(2)
        expect(page.locator('.vs-row-selected')).to_have_count(2)
        expect(page.locator(
            '.vs-record-navigation-position')).to_contain_text('#2')
        with page.expect_response(
                lambda response: (
                    '/select?' in response.url
                    and 'row=true' in response.url)):
            sibling_name.click(modifiers=['Control'])
        expect(page.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(1)
        expect(parent).to_have_class(
            re.compile(r'\bvs-row-selected\b'))
        page.reload(wait_until='domcontentloaded')
        parent = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Parent"]'))
        expect(parent.get_by_role(
                'checkbox', name='Select record')).to_be_checked()
        expect(parent.get_by_text('•', exact=True)).to_be_visible()
        expect(parent.locator(
            '.vs-tree-affix', has_text='€')).to_be_visible()
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

        sibling_name = page.locator('input[value="Tree Sibling"]')
        with page.expect_response(
                lambda response: (
                    '/select?' in response.url
                    and 'row=true' in response.url)):
            sibling_name.click(modifiers=['Shift'])
        expect(page.locator(
            '.vs-select-column input[aria-label="Select record"]:checked'
            )).to_have_count(3)
        expect(page.locator('.vs-row-selected')).to_have_count(3)
        expect(page.locator(
            '.vs-record-navigation-position')).to_contain_text('#3')

        parent = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Parent"]'))
        sibling = page.locator(
            '.vs-row', has=page.locator(
                'input[value="Tree Sibling"]'))
        expect(page.get_by_role(
            'button', name='Move down')).to_have_count(0)
        expect(parent.locator(
            '[data-tree-drag-handle]')).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith('/tree/move')):
            parent.locator('[data-tree-drag-handle]').drag_to(
                sibling.locator('[data-tree-drag-handle]'))
        expect(rows.nth(0).locator(
                'input[value="Tree Sibling"]')).to_be_visible()
        page.get_by_role('button', name='Save', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(rows.nth(0).locator(
                'input[value="Tree Sibling"]')).to_be_visible()

        global_search = page.get_by_label('Global search')
        global_search.fill('Cassini Sequence List')
        page.locator(
            '[data-global-search-result]',
            has_text='Cassini Sequence List').click()
        flat_rows = page.locator(
            '.vs-active-panel > .vs-screen .vs-row')
        expect(flat_rows).to_have_count(2)
        expect(flat_rows.nth(0).locator(
            'text=Tree Sibling')).to_be_visible()
        flat_sibling = flat_rows.filter(has_text='Tree Sibling')
        flat_parent = flat_rows.filter(has_text='Tree Parent')
        flat_parent_box = flat_parent.bounding_box()
        with page.expect_response(
                lambda response: response.url.endswith('/tree/move')):
            flat_sibling.locator('[data-tree-drag-handle]').drag_to(
                flat_parent,
                target_position={
                    'x': 20,
                    'y': flat_parent_box['height'] - 1,
                    })
        expect(flat_rows.nth(0)).to_contain_text('Tree Parent')
        page.get_by_role('button', name='Save', exact=True).click()
        page.reload(wait_until='domcontentloaded')
        expect(flat_rows.nth(0)).to_contain_text('Tree Parent')

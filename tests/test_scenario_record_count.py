from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestRecordCount(WebTestCase):
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

            Node.create([
                    {
                        'name': 'Count record %05d' % index,
                        'sequence': index,
                        }
                    for index in range(11745)
                    ])
            view, = View.create([{
                        'model': 'cassini.test.tree.node',
                        'type': 'tree',
                        'data': '<tree><field name="name"/></tree>',
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Record Count',
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
            Menu.create([{
                        'name': 'Cassini Record Count',
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
            'button', name='Cassini Record Count', exact=True).click()

        position = page.locator('.vs-record-navigation-position')
        pages = page.locator('.vs-page-navigation-position')
        expect(position.locator(':scope > span')).to_have_text('_@1000/')
        expect(pages.locator(':scope > span')).to_have_text('1/')
        page_count = pages.get_by_role('button', name='+1', exact=True)
        expect(page_count).to_be_visible()
        expect(page_count).to_have_attribute(
            'title', 'Click to see the number of pages')
        with page.expect_response(
                lambda response: response.url.endswith('/page/next')):
            page.get_by_role('button', name='Next page').click()

        position = page.locator('.vs-record-navigation-position')
        pages = page.locator('.vs-page-navigation-position')
        expect(position.locator(':scope > span')).to_have_text('_@2000/')
        expect(pages.locator(':scope > span')).to_have_text('2/')
        page_count = pages.get_by_role('button', name='+2', exact=True)
        expect(page_count).to_be_visible()
        expect(page_count).to_have_attribute(
            'title', 'Click to see the number of pages')
        with page.expect_response(
                lambda response: '/select?row=true' in response.url):
            page.get_by_text('Count record 01000', exact=True).click()
        expect(position.locator(':scope > span')).to_have_text('1001@2000/')
        count = position.get_by_role('button', name='+1k', exact=True)
        expect(count).to_be_visible()
        expect(count).to_have_attribute(
            'title', 'Click to see the number of records')
        self.assertTrue(count.get_attribute('hx-post').endswith(
                '/records/count'))
        self.assertEqual(
            page_count.get_attribute('hx-post'), count.get_attribute('hx-post'))

        with page.expect_response(
                lambda response: response.url.endswith('/records/count')):
            page_count.click()
        expect(position.locator(
                ':scope > span')).to_have_text('1001@2000/11.75k')
        expect(position.locator(
                ':scope > span')).to_have_attribute('title', '11,745')
        expect(position.get_by_role(
                'button', name='+1k', exact=True)).to_have_count(0)
        expect(pages).to_have_text('2/12')
        expect(pages).to_have_attribute('title', '12')
        expect(pages.get_by_role(
                'button', name='+2', exact=True)).to_have_count(0)

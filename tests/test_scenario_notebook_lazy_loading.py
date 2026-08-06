from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestNotebookLazyLoading(WebTestCase):
    modules = ['cassini']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')
            Widget = pool.get('cassini.test.widget')

            Widget.create([{'char_value': 'Notebook record'}])
            form_view, = View.create([{
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form>'
                            '<field name="char_value"/>'
                            '<notebook>'
                            '<page id="first" string="First">'
                            '<separator id="initial" '
                            'string="Initial Page Content"/>'
                            '</page>'
                            '<page id="more" string="More">'
                            '<separator id="lazy" '
                            'string="Lazy Page Content"/>'
                            '</page>'
                            '</notebook>'
                            '</form>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Lazy Notebook',
                        'res_model': 'cassini.test.widget',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': form_view.id,
                        'act_window': action.id,
                        }])
            Menu.create([{
                        'name': 'Cassini Lazy Notebook',
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
            'button', name='Cassini Lazy Notebook', exact=True).click()

        notebook = page.locator('.vs-notebook')
        first_tab = notebook.get_by_role('tab', name='First', exact=True)
        more_tab = notebook.get_by_role('tab', name='More', exact=True)
        more_page = notebook.locator(
            '[role="tabpanel"][data-notebook-page="1"]')
        expect(first_tab).to_have_attribute('aria-selected', 'true')
        expect(more_tab).to_have_attribute('aria-selected', 'false')
        expect(more_page).to_be_hidden()
        expect(more_page.get_by_text(
            'Lazy Page Content', exact=True)).to_have_count(0)
        expect(more_page.locator(
            '[hx-get][hx-trigger="intersect"]')).to_have_count(1)
        expect(more_page.locator(
            '[role="status"][aria-label="Loading"]')).to_have_count(1)
        page.evaluate(
            'window.__cassiniNotebookScreen = '
            'document.querySelector(".vs-screen")')
        notebook_requests = []
        page.on('request', lambda request: (
                notebook_requests.append(request)
                if '/notebook/' in request.url else None))

        with page.expect_response(
                lambda response: response.url.endswith(
                    '/content')) as lazy_response:
            more_tab.click()
        self.assertEqual(lazy_response.value.request.method, 'GET')
        self.assertEqual(len([
                    request for request in notebook_requests
                    if '/page/1' in request.url]), 1)
        expect(more_tab).to_have_attribute('aria-selected', 'true')
        expect(first_tab).to_have_attribute('aria-selected', 'false')
        expect(more_page).to_be_visible()
        expect(more_page.get_by_text(
            'Lazy Page Content', exact=True)).to_be_visible()
        self.assertTrue(page.evaluate(
            'window.__cassiniNotebookScreen === '
            'document.querySelector(".vs-screen")'))

        with page.expect_response(
                lambda response: response.url.endswith('/page/0')):
            first_tab.click()
        self.assertEqual(len([
                    request for request in notebook_requests
                    if '/page/0' in request.url]), 1)
        expect(first_tab).to_have_attribute('aria-selected', 'true')
        expect(more_page).to_be_hidden()

from urllib.parse import urljoin

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestDocumentWidget(WebTestCase):
    modules = ['cassini']
    timeout = 10000

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

            Widget.create([{
                        'binary_value': b'%PDF-1.4\n%%EOF',
                        'binary_filename': 'preview.pdf',
                        'char_value': 'Document Widget',
                        'document_value': (
                            b'<html><body>Cassini document preview</body>'
                            b'</html>'),
                        'document_filename': 'preview.html',
                        }])
            view, = View.create([{
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form>'
                            '<field name="document_value" '
                            'widget="document" '
                            'filename="document_filename" height="320"/>'
                            '<field name="binary_value" '
                            'widget="document" '
                            'filename="binary_filename" height="240"/>'
                            '</form>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Document Widget',
                        'res_model': 'cassini.test.widget',
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
                        'name': 'Cassini Document Widget',
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
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            page.get_by_role(
                'button', name='Cassini Document Widget', exact=True).click()

        html_document = page.locator('[data-field="document_value"]')
        html_frame = html_document.locator('iframe.vs-document-content')
        expect(html_frame).to_have_attribute('sandbox', '')
        expect(html_frame).to_have_attribute('style', 'height:320px')
        expect(html_document.locator('.vs-binary-widget')).to_have_count(0)
        expect(page.frame_locator(
            '[data-field="document_value"] iframe').get_by_text(
                'Cassini document preview')).to_be_visible()

        html_url = urljoin(page.url, html_frame.get_attribute('src'))
        html_response = page.context.request.get(html_url)
        self.assertTrue(html_response.ok)
        self.assertEqual(
            html_response.headers['content-type'], 'text/html')
        self.assertEqual(
            html_response.headers['content-disposition'],
            'inline; filename="preview.html"')
        self.assertIn('no-store', html_response.headers['cache-control'])

        pdf_document = page.locator('[data-field="binary_value"]')
        pdf_object = pdf_document.locator('object.vs-document-content')
        expect(pdf_object).to_have_attribute('type', 'application/pdf')
        expect(pdf_object).to_have_attribute('style', 'height:240px')
        expect(pdf_document.locator('.vs-binary-widget')).to_have_count(0)

        pdf_url = urljoin(page.url, pdf_object.get_attribute('data'))
        pdf_response = page.context.request.get(pdf_url)
        self.assertTrue(pdf_response.ok)
        self.assertEqual(
            pdf_response.headers['content-type'], 'application/pdf')
        self.assertEqual(
            pdf_response.headers['content-disposition'],
            'inline; filename="preview.pdf"')

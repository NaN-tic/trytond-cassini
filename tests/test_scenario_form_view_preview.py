import re

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestFormViewPreview(WebTestCase):
    modules = ['cassini', 'account_invoice']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ModelData = pool.get('ir.model.data')
            Site = pool.get('www.site')

            cls.show_view_action = ModelData.get_id('ir', 'act_view_show')
            cls.account_view = ModelData.get_id(
                'account', 'account_view_form')
            cls.payment_term_line_view = ModelData.get_id(
                'account_invoice', 'payment_term_line_view_form')
            cls.edocument_start_view = ModelData.get_id(
                'account_invoice', 'edocument_start_view_form')
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
        page.wait_for_url(re.compile(r'/cassini/app'))

        def show(view_id):
            page.evaluate(
                '''url => htmx.ajax("POST", url, {
                    target: "#workspace", swap: "outerHTML"})''',
                (
                    f'/{self.database}/cassini/open/action/'
                    f'{self.show_view_action}?model=ir.ui.view'
                    f'&record={view_id}'))
            wizard = page.locator('.vs-wizard-dialog')
            expect(wizard).to_be_visible()
            return wizard

        def close(wizard):
            wizard.locator(
                '.vs-dialog-actions > button[data-modal-cancel=true]').click()
            expect(wizard).not_to_be_visible()

        wizard = show(self.account_view)
        expect(wizard.get_by_role(
            'tab', name='General Information', exact=True)).to_be_visible()
        expect(wizard.get_by_role(
            'tab', name='Children', exact=True)).to_be_visible()
        expect(wizard.get_by_role(
            'tab', name='Note', exact=True)).to_be_visible()
        expect(wizard.get_by_role(
            'tab', name='General Ledger', exact=True)).to_have_count(0)
        name_label = wizard.locator('label[for]', has_text='Name').first
        expect(name_label).to_be_visible()
        self.assertNotIn('\n', name_label.inner_text())
        self.assertLess(name_label.bounding_box()['height'], 32)
        self.assertGreater(
            wizard.bounding_box()['width'],
            page.viewport_size['width'] * .9)
        close(wizard)

        wizard = show(self.payment_term_line_view)
        expect(wizard.locator(
            '[data-field="relativedeltas"] .vs-x2many-form')).to_be_visible()
        expect(wizard.locator(
            '[data-field="relativedeltas"] '
            '.vs-x2many-table')).to_have_count(0)
        expect(wizard.get_by_text(
            'Number of Months', exact=True)).to_be_visible()
        expect(wizard.get_by_text(
            'Payment Term Line', exact=True)).to_have_count(0)
        expect(wizard.locator(
            '[data-field="type"] select')).to_have_value('')
        close(wizard)

        wizard = show(self.edocument_start_view)
        expect(wizard.locator(
            '[data-field="format"] select')).to_have_value('')
        expect(wizard.locator(
            '[data-field="template"] select')).to_have_value('')
        expect(wizard.locator(
            'label[for]', has_text='Template')).to_be_visible()
        close(wizard)

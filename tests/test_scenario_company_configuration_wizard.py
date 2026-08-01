from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestCompanyConfigurationWizard(WebTestCase):
    modules = ['cassini', 'company']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ConfigItem = pool.get('ir.module.config_wizard.item')
            Currency = pool.get('currency.currency')
            ModelData = pool.get('ir.model.data')
            Party = pool.get('party.party')
            Site = pool.get('www.site')

            ConfigItem.write(ConfigItem.search([]), {'state': 'done'})
            company_item = ConfigItem(ModelData.get_id(
                    'company', 'config_wizard_item_company'))
            ConfigItem.write([company_item], {'state': 'open'})
            Party.create([{'name': 'Setup Party'}])
            Currency.create([{
                        'name': 'Euro',
                        'symbol': '€',
                        'code': 'EUR',
                        'rounding': Decimal('0.01'),
                        'digits': 2,
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

        page.get_by_role('button', name='OK', exact=True).click()
        expect(page.get_by_role(
            'heading', name='Configure Company')).to_be_visible()
        expect(page.get_by_text(
            'You can now add your company into the system.',
            exact=True)).to_be_visible()
        page.get_by_role('button', name='OK', exact=True).click()

        company = page.locator('.vs-wizard')
        party = company.locator(
            '[data-field="party"] [data-relation-input]')
        with page.expect_response(
                lambda response: '/field/party/autocomplete' in response.url):
            party.fill('Setup')
        suggestion = company.locator(
            '[data-field="party"] .vs-relation-option',
            has_text='Setup Party')
        expect(suggestion).to_be_visible()
        with page.expect_response(
                lambda response: '/wizard/field/party' in response.url):
            suggestion.click()
        expect(company.locator(
            '[data-field="party"] [data-relation-input]')).to_have_value(
                'Setup Party')

        currency = company.locator('[data-field="currency"]')
        currency.get_by_role('button', name='Search a record').click()
        search = page.get_by_role('dialog', name='Search Currency')
        expect(search).to_be_visible()
        euro = search.locator(
            '[data-relation-search-row]', has_text='EUR')
        euro.click()
        expect(search.get_by_role(
            'button', name='OK', exact=True)).to_be_enabled()
        search.get_by_role('button', name='OK', exact=True).click()
        expect(company.locator(
            '[data-field="currency"] [data-relation-input]')).to_have_value(
                'Euro')

        party = company.locator(
            '[data-field="party"] [data-relation-input]')
        open_tab_count = page.locator('#workspace-tabs .vs-tab').count()
        party.press('F3')
        relation_dialog = page.locator('.vs-relation-record-dialog')
        relation_name = relation_dialog.locator(
            '[data-field="name"] input')
        expect(relation_name).to_be_visible()
        expect(relation_name).to_be_focused()
        expect(relation_dialog.locator('.vs-toolbar')).to_have_count(0)
        expect(page.locator(
            '#workspace-tabs .vs-tab')).to_have_count(open_tab_count)
        relation_dialog.get_by_role(
            'button', name='Cancel', exact=True).click()
        unsaved = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(unsaved).to_be_visible()
        unsaved.get_by_role(
            'button', name='Close without saving', exact=True).click()
        expect(company).to_be_visible()

        employees = company.locator('[data-field="employees"]')
        employees.get_by_role('button', name='New', exact=True).click()
        employee = page.locator('.vs-relation-record-dialog')
        expect(employee).to_be_visible()
        expect(page.locator(
            '#workspace-tabs .vs-tab')).to_have_count(open_tab_count)
        expect(employee.locator(
            '[data-field="party"] [data-relation-input]')).to_be_visible()
        employee_party = employee.locator(
            '[data-field="party"] [data-relation-input]')
        with page.expect_response(
                lambda response: '/field/party/autocomplete' in response.url):
            employee_party.fill('Setup')
        employee_suggestion = employee.locator(
            '[data-field="party"] .vs-relation-option',
            has_text='Setup Party')
        with page.expect_response(
                lambda response: '/field/party' in response.url):
            employee_suggestion.click()
        employee.get_by_role(
            'button', name='OK', exact=True).click()
        expect(employee).not_to_be_visible()

        company = page.locator('.vs-wizard')
        expect(company.locator(
            '[data-field="employees"] .vs-x2many-row')).to_have_count(1)
        employees = company.locator('[data-field="employees"]')
        employees.get_by_role('button', name='Switch', exact=True).click()
        expect(company.locator(
            '[data-field="employees"] .vs-x2many-form')).to_be_visible()
        company.locator('[data-field="employees"]').get_by_role(
            'button', name='Switch', exact=True).click()
        expect(company.locator(
            '[data-field="employees"] .vs-x2many-table')).to_be_visible()
        expect(page.get_by_text('Unknown record', exact=True)).to_have_count(0)
        page.get_by_role('button', name='Add', exact=True).click()
        expect(page.get_by_text(
            'The configuration is done.', exact=True)).to_be_visible()

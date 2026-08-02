from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestRelationDomainCreation(WebTestCase):
    modules = ['cassini', 'account_invoice']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Company = pool.get('company.company')
            Currency = pool.get('currency.currency')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Party = pool.get('party.party')
            PartyCategory = pool.get('party.category')
            Site = pool.get('www.site')
            User = pool.get('res.user')

            currency, = Currency.create([{
                        'name': 'Cassini Euro',
                        'symbol': '€',
                        'code': 'QAE',
                        'rounding': Decimal('0.01'),
                        'digits': 2,
                        }])
            company_party, = Party.create([{
                        'name': 'Cassini Relation Company',
                        }])
            company, = Company.create([{
                        'party': company_party.id,
                        'currency': currency.id,
                        }])
            PartyCategory.create([{
                        'name': 'Cassini Party Category',
                        }])
            User.write([User(1)], {
                    'companies': [('add', [company.id])],
                    'company': company.id,
                    })

            fiscalyear_action = ActionWindow(ModelData.get_id(
                    'account', 'act_fiscalyear_form'))
            party_action = ActionWindow(ModelData.get_id(
                    'party', 'act_party_form'))
            Menu.create([{
                        'name': 'Cassini Fiscal Year Relations',
                        'action': str(fiscalyear_action),
                        }, {
                        'name': 'Cassini Party Relations',
                        'action': str(party_action),
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
        global_search = page.get_by_label('Global search')
        global_search.fill('Cassini Fiscal Year Relations')
        fiscalyear_result = page.locator(
            '[data-global-search-result]',
            has_text='Cassini Fiscal Year Relations')
        expect(fiscalyear_result).to_be_visible()
        fiscalyear_result.click()
        expect(page.locator(
            '#global-search-results .vs-search-results')).not_to_be_visible()
        page.get_by_role('button', name='New', exact=True).click()
        expect(page.locator(
            '[data-field="name"] input')).to_be_visible()
        sequences_page = page.locator(
            '.vs-local-tab-title', has_text='Sequences')
        sequences_page.click()
        expect(sequences_page).to_have_attribute('aria-selected', 'true')
        expect(page.locator('.vs-screen .htmx-request')).to_have_count(0)

        move_sequence = page.locator(
            '[data-field="move_sequence"] [data-relation-input]')
        expect(move_sequence).to_be_editable()
        move_sequence.focus()
        expect(move_sequence).to_be_focused()
        move_sequence.press('F3')
        sequence = page.locator('.vs-relation-record-dialog')
        expect(sequence.locator('.vs-form')).to_be_visible()
        expect(sequence.locator('.vs-tree')).to_have_count(0)
        expect(sequence.locator(
            '[data-field="sequence_type"] '
            'option:checked')).to_have_text('Account Move')
        expect(sequence.locator(
            '[data-field="company"] '
            '[data-relation-input]')).to_have_value(
                'Cassini Relation Company')
        page.keyboard.press('Escape')
        discard = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(discard).to_be_visible()
        expect(sequence).to_be_visible()
        discard.get_by_role(
            'button', name='Close without saving', exact=True).click()
        expect(sequence).not_to_be_visible()

        invoice_sequences = page.locator(
            '[data-field="invoice_sequences"]')
        invoice_sequences.get_by_role(
            'button', name='New', exact=True).click()
        invoice_sequence = page.locator('.vs-relation-record-dialog')
        expect(invoice_sequence.locator('.vs-form')).to_be_visible()
        expect(invoice_sequence.locator('.vs-tree')).to_have_count(0)
        expect(invoice_sequence.locator(
            '[data-field="fiscalyear"]')).to_have_count(0)
        expect(invoice_sequence.locator(
            '[data-field="company"] '
            '[data-relation-input]')).to_have_value(
                'Cassini Relation Company')
        invoice_sequence.get_by_role(
            'button', name='Cancel', exact=True).click()
        page.get_by_role(
            'alertdialog', name='Unsaved changes').get_by_role(
                'button', name='Close without saving', exact=True).click()

        page.locator('.vs-tab-active .vs-tab-close').click()
        page.get_by_role(
            'alertdialog', name='Unsaved changes').get_by_role(
                'button', name='Close without saving', exact=True).click()
        global_search = page.get_by_label('Global search')
        global_search.fill('Cassini Party Relations')
        party_result = page.locator(
            '[data-global-search-result]',
            has_text='Cassini Party Relations')
        expect(party_result).to_be_visible()
        party_result.click()
        page.get_by_role('button', name='New', exact=True).click()
        addresses = page.locator('[data-field="addresses"]')
        addresses.get_by_role('button', name='New', exact=True).click()
        address = page.locator('.vs-relation-record-dialog')
        expect(address.locator('.vs-form')).to_be_visible()
        expect(address.locator('.vs-tree')).to_have_count(0)
        expect(address.locator('[data-field="party"]')).to_have_count(0)
        expect(address.locator('[data-field="street"]')).to_be_visible()
        address.get_by_role(
            'button', name='Cancel', exact=True).click()
        page.get_by_role(
            'alertdialog', name='Unsaved changes').get_by_role(
                'button', name='Close without saving', exact=True).click()
        expect(address).not_to_be_visible()

        categories = page.locator('[data-field="categories"]')
        expect(categories.locator(
            '.vs-many2many-panel')).to_be_visible()
        category_input = categories.locator(
            '[data-many2many-input]')
        expect(category_input).to_be_editable()
        self.assertIn(
            '/field/categories/autocomplete',
            category_input.get_attribute('hx-post'))
        with page.expect_response(
                lambda response:
                '/field/categories/autocomplete' in response.url):
            category_input.fill('Cassini Party Category')
        category_option = categories.locator(
            '.vs-relation-option', has_text='Cassini Party Category')
        expect(category_option).to_be_visible()
        category_option.click()
        expect(page.locator(
            '[data-field="categories"]')).to_contain_text(
                'Cassini Party Category')

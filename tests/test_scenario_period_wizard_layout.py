from datetime import date
from decimal import Decimal

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestPeriodWizardLayout(WebTestCase):
    modules = ['cassini', 'account']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Company = pool.get('company.company')
            Currency = pool.get('currency.currency')
            FiscalYear = pool.get('account.fiscalyear')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Party = pool.get('party.party')
            Sequence = pool.get('ir.sequence.strict')
            Site = pool.get('www.site')
            User = pool.get('res.user')

            currency, = Currency.create([{
                        'name': 'Cassini Period Euro',
                        'symbol': '€',
                        'code': 'QPE',
                        'rounding': Decimal('0.01'),
                        'digits': 2,
                        }])
            company_party, = Party.create([{
                        'name': 'Cassini Period Company',
                        }])
            company, = Company.create([{
                        'party': company_party.id,
                        'currency': currency.id,
                        }])
            User.write([User(1)], {
                    'companies': [('add', [company.id])],
                    'company': company.id,
                    })
            sequence, = Sequence.create([{
                        'name': 'Cassini Account Moves',
                        'sequence_type': ModelData.get_id(
                            'account', 'sequence_type_account_move'),
                        'company': company.id,
                        }])
            fiscalyear, = FiscalYear.create([{
                        'name': 'Cassini Fiscal Year 2026',
                        'start_date': date(2026, 1, 1),
                        'end_date': date(2026, 12, 31),
                        'move_sequence': sequence.id,
                        'company': company.id,
                        }])
            action, = ActionWindow.create([{
                        'name': 'Cassini Period Layout',
                        'res_model': 'account.fiscalyear',
                        'domain': '[["id", "=", %d]]' % fiscalyear.id,
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Cassini Period Layout',
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

        search = page.get_by_label('Global search')
        search.fill('Cassini Period Layout')
        page.locator(
            '[data-global-search-result]',
            has_text='Cassini Period Layout').click()
        row = page.get_by_role('row').filter(
            has_text='Cassini Fiscal Year 2026')
        expect(row).to_be_visible()
        row.dblclick()
        page.get_by_role(
            'button', name='Create Periods', exact=True).click()

        wizard = page.locator('.vs-wizard-dialog')
        expect(wizard).to_be_visible()
        end_day_label = wizard.locator(
            'label', has_text='End Day')
        end_day_field = wizard.locator('[data-field="end_day"]')
        expect(end_day_label).to_be_visible()
        expect(end_day_field).to_be_visible()
        label_box = end_day_label.bounding_box()
        field_box = end_day_field.bounding_box()
        self.assertIsNotNone(label_box)
        self.assertIsNotNone(field_box)
        self.assertLess(
            abs(
                label_box['y'] + label_box['height'] / 2
                - field_box['y'] - field_box['height'] / 2),
            3)

        page.keyboard.press('Escape')
        expect(wizard).not_to_be_visible()
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    'Cassini Fiscal Year 2026')

        page.get_by_role(
            'button', name='Create Periods', exact=True).click()
        expect(wizard).to_be_visible()
        wizard.get_by_role(
            'button', name='Create', exact=True).click()
        expect(wizard).not_to_be_visible()
        expect(page.locator(
            '[data-field="periods"] .vs-x2many-row')).to_have_count(12)

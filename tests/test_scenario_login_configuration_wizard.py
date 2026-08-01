from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestLoginConfigurationWizard(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ConfigItem = pool.get('ir.module.config_wizard.item')
            ModelData = pool.get('ir.model.data')
            Site = pool.get('www.site')

            items = ConfigItem.search([])
            ConfigItem.write(items, {'state': 'done'})
            language_item = ConfigItem(ModelData.get_id(
                    'ir', 'config_wizard_item_lang'))
            ConfigItem.write([language_item], {'state': 'open'})
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

        wizard_tab = page.locator(
            '.vs-tab', has_text='Module Configuration')
        expect(wizard_tab).to_be_visible()
        wizard = page.locator('.vs-wizard')
        expect(wizard).to_be_visible()
        expect(page.get_by_role(
            'button', name='Cancel', exact=True)).to_be_visible()
        title = wizard.get_by_role(
            'heading', name='Module Configuration')
        information = wizard.locator('.vs-form-image')
        message = wizard.get_by_text(
            'You will be able to configure your installation depending '
            'on the modules you have installed.', exact=True)
        title_box = title.bounding_box()
        information_box = information.bounding_box()
        message_box = message.bounding_box()
        self.assertLess(title_box['y'], information_box['y'])
        self.assertLess(
            abs(information_box['y'] - message_box['y']), 20)
        self.assertGreater(message_box['width'], 600)
        self.assertLessEqual(
            message.evaluate('element => element.scrollHeight'), 32)
        self.assertGreaterEqual(float(message.evaluate(
                    'element => parseFloat(getComputedStyle(element).fontSize)')),
            14)

        page.reload(wait_until='domcontentloaded')
        expect(wizard_tab).to_have_count(1)
        expect(page.locator('.vs-wizard')).to_be_visible()

        page.get_by_role('button', name='OK', exact=True).click()
        language_title = page.get_by_role(
            'heading', name='Configure Languages')
        expect(language_title).to_be_visible()
        languages = page.locator(
            '.vs-wizard [data-field="languages"] select[multiple]')
        expect(languages).to_be_visible()
        self.assertGreaterEqual(languages.locator('option').count(), 10)
        self.assertGreaterEqual(
            languages.locator('option:checked').count(), 1)
        expect(languages.locator('option', has_text='English')).to_be_visible()
        expect(languages.locator('option', has_text='Català')).to_be_visible()
        languages_box = languages.bounding_box()
        self.assertGreater(languages_box['width'], 600)
        self.assertGreater(languages_box['height'], 140)
        bulgarian = languages.locator('option', has_text='Bulgarian')
        selected = bulgarian.evaluate('option => option.selected')
        with page.expect_response(
                lambda response: '/wizard/field/languages' in response.url):
            bulgarian.dispatch_event('mousedown')
        bulgarian = page.locator(
            '.vs-wizard [data-field="languages"] select[multiple] '
            'option', has_text='Bulgarian')
        self.assertNotEqual(
            bulgarian.evaluate('option => option.selected'), selected)

        languages = page.locator(
            '.vs-wizard [data-field="languages"] select[multiple]')
        with page.expect_response(
                lambda response: '/wizard/field/languages' in response.url):
            languages.select_option(label=['English', 'Català', 'Spanish'])
        languages = page.locator(
            '.vs-wizard [data-field="languages"] select[multiple]')
        self.assertEqual(
            set(languages.locator('option:checked').all_text_contents()),
            {'English', 'Català', 'Spanish'})

        page.get_by_role('button', name='Load', exact=True).click()
        expect(page.get_by_text(
            'The configuration is done.', exact=True)).to_be_visible()
        expect(page.get_by_text(
            'The default language "English" must be translatable.',
            exact=True)).to_have_count(0)
        page.get_by_role('button', name='OK', exact=True).click()
        expect(page.locator('.vs-wizard')).not_to_be_visible()
        page.reload(wait_until='domcontentloaded')
        expect(wizard_tab).to_have_count(0)

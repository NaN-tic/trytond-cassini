from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


MODULE_ROOT = Path(__file__).resolve().parent.parent


class TestPreferencesNavigation(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            Lang = pool.get('ir.lang')
            Translation = pool.get('ir.translation')
            User = pool.get('res.user')

            catalan, = Lang.search([('code', '=', 'ca')], limit=1)
            Lang.write([catalan], {'translatable': True})
            Translation.translation_import(
                'ca', 'cassini', str(MODULE_ROOT / 'locale' / 'ca.po'))

            action, = ActionWindow.create([{
                        'name': 'Preference Navigation Groups',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Preference Navigation Groups',
                        'action': str(action),
                        }])
            Group.create([{'name': 'Existing Preference Group'}])
            administrator = User(1)
            user, = User.create([{
                        'name': 'Cassini Preferences Tester',
                        'login': 'cassini-preferences-tester',
                        'password': cls.password,
                        'groups': [('add', [
                                    group.id
                                    for group in administrator.groups])],
                        }])
            cls.user = user.login
            cls.user_name = user.name
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @browser()
    def test(self, page: Page):
        with Transaction().start(self.database, 1):
            Site = Pool().get('www.site')
            site, = Site.search([('type', '=', 'cassini')], limit=1)
            self.assertIsNone(site.get_cache(
                    None,
                    SimpleNamespace(args={'_cassini_reload': '1'})))

        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        page.locator('[data-panel-option="menu"]').click()
        page.get_by_role(
            'button', name='Preference Navigation Groups',
            exact=True).click()
        expect(page.locator('.vs-tab')).to_have_count(1)

        page.get_by_role('button', name='User menu').click()
        page.get_by_role(
            'menuitem', name='Preferences', exact=True).click()
        close_tabs = page.get_by_role(
            'alertdialog', name='Close all tabs?')
        expect(close_tabs).to_be_visible()
        expect(page.locator('#preferences-title')).not_to_be_visible()
        close_tabs.get_by_role(
            'button', name='Cancel', exact=True).click()
        expect(close_tabs).not_to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(1)

        page.get_by_role('button', name='New', exact=True).click()
        group_name = page.locator('[data-field="name"] input')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            group_name.press_sequentially('Discarded Preference Group')

        page.get_by_role('button', name='User menu').click()
        page.get_by_role(
            'menuitem', name='Preferences', exact=True).click()
        close_tabs = page.get_by_role(
            'alertdialog', name='Close all tabs?')
        close_tabs.get_by_role(
            'button', name='Close tabs and continue',
            exact=True).click()

        unsaved = page.get_by_role(
            'alertdialog', name='Unsaved changes')
        expect(unsaved).to_be_visible()
        expect(unsaved.get_by_text(
                'Discarded Preference Group', exact=True)).to_be_visible()
        unsaved.get_by_role(
            'button', name='Close without saving', exact=True).click()

        preferences = page.locator('.vs-preferences-dialog')
        expect(preferences).to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(0)

        name = preferences.locator('[data-field="name"] input')
        name.press('Control+A')
        with page.expect_response(
                lambda response: '/preferences/field/name' in response.url):
            name.press_sequentially('Cassini Preferences User')

        with page.expect_response(
                lambda response:
                '/preferences/notebook/' in response.url
                and response.url.endswith('/page/4')):
            preferences.get_by_role(
                'tab', name='Preferences', exact=True).click()
        language = preferences.locator('[data-field="language"] select')
        with page.expect_response(
                lambda response:
                '/preferences/field/language' in response.url):
            language.select_option('ca')

        save = preferences.get_by_role(
            'button', name='Save', exact=True)
        self.assertIsNone(save.get_attribute('hx-post'))
        preferences_form = preferences.locator('#preferences-form')
        self.assertTrue(
            preferences_form.get_attribute('action').endswith(
                '/preferences/save'))
        expect(preferences_form).to_have_attribute(
            'method', 'post')
        with page.expect_navigation(
                wait_until='domcontentloaded') as navigation:
            with page.expect_response(
                    lambda response:
                    response.url.endswith('/preferences/save')) as saved:
                save.click()
        self.assertEqual(saved.value.status, 303)
        self.assertIn(
            '?_cassini_reload=', saved.value.headers.get('location', ''))
        self.assertIn(
            'no-store', navigation.value.headers.get('cache-control', ''))
        self.assertTrue(page.url.endswith('/cassini/app'))
        expect(page.locator('#preferences-title')).not_to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(0)
        expect(page.locator('html')).to_have_attribute('lang', 'ca')
        expect(page.get_by_role(
            'button', name="Menú de l'usuari")).to_contain_text(
                'Cassini Preferences User')
        expect(page.get_by_role(
            'button', name='Menú', exact=True)).to_be_visible()

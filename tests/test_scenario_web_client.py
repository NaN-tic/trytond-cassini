from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestWebClient(WebTestCase):
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
            Notification = pool.get('res.notification')
            Site = pool.get('www.site')

            action, = ActionWindow.create([{
                        'name': 'Cassini Groups',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Cassini Groups',
                        'action': str(action),
                        }, {
                        'name': (
                            'Cassini Groups With A Deliberately Long '
                            'Suggestion'),
                        'action': str(action),
                        }])
            Group.create([{'name': 'Persistent Existing Group'}])
            Notification.create([{
                        'user': 1,
                        'label': 'Cassini notification',
                        'description': 'Persistent notification menu',
                        }])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    def setUp(self):
        super().setUp()

    def tearDown(self):
        super().tearDown()

    @browser()
    def test(self, page: Page):
        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        expect(page.get_by_role(
                'heading', name='Sign in')).to_be_visible()
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        sign_in = page.get_by_role('button', name='Sign in')
        sign_in.hover()
        sign_in_colors = sign_in.evaluate(
            '''element => ({
                background: getComputedStyle(element).backgroundColor,
                foreground: getComputedStyle(element).color,
            })''')
        self.assertNotEqual(
            sign_in_colors['foreground'], sign_in_colors['background'])
        sign_in.click()
        page.locator('[data-panel-option="menu"]').click()

        expect(page.locator('.vs-app')).to_be_visible()
        expect(page.locator('#main-menu .vs-menu-title')).to_have_count(0)
        page.get_by_role(
            'button', name='Cassini Groups', exact=True).click()
        expect(page.get_by_text('Persistent Existing Group')).to_be_visible()

        page.get_by_role('button', name='New', exact=True).click()
        name = page.locator('[data-field="name"] input')
        with page.expect_response(
                lambda response: '/field/name' in response.url):
            name.press_sequentially('Unsaved Group Survives Reload')
        expect(page.get_by_text('Unsaved changes')).to_be_visible()

        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
                '[data-field="name"] input')).to_have_value(
                    'Unsaved Group Survives Reload')
        expect(page.locator('.vs-tab')).to_have_count(1)

        page.get_by_role('button', name='Save', exact=True).click()
        expect(page.get_by_text('Unsaved changes')).not_to_be_visible()

        global_search = page.get_by_label('Global search')
        global_search_width = global_search.bounding_box()['width']
        global_search.focus()
        page.wait_for_function(
            '''width => document.querySelector(
                '[data-global-search-input]').getBoundingClientRect().width
                > width''', arg=global_search_width)
        self.assertGreater(
            global_search.bounding_box()['width'], global_search_width)
        page.get_by_role('button', name='User menu').click()
        expect(page.locator('.vs-notification-badge')).to_have_text('1')
        expect(page.get_by_text(
                'Cassini notification', exact=True)).to_be_visible()
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/shell/user-close')):
            global_search.click()
        expect(page.locator('.vs-user-menu')).to_have_count(0)
        expect(page.get_by_role(
            'button', name='User menu')).to_have_attribute(
                'aria-expanded', 'false')

        page.get_by_role('button', name='User menu').click()
        expect(page.get_by_text(
                'Cassini notification', exact=True)).to_be_visible()
        page.get_by_text(
            'Cassini notification', exact=True).click()
        expect(page.locator('.vs-user-menu')).to_have_count(0)
        page.get_by_role('button', name='User menu').click()
        expect(page.locator('.vs-notification-badge')).to_have_count(0)
        preferences = page.get_by_role(
            'menuitem', name='Preferences', exact=True)
        expect(preferences.locator(
            'img[src$="tryton-launch.svg"]')).to_be_visible()
        preferences.click()
        close_tabs = page.get_by_role(
            'alertdialog', name='Close all tabs?')
        expect(close_tabs).to_be_visible()
        close_tabs.get_by_role(
            'button', name='Close tabs and continue', exact=True).click()
        expect(page.locator('#preferences-title')).to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(0)
        page.get_by_role('button', name='Cancel').click()

        global_search.evaluate(
            'element => { window.cassiniGlobalSearch = element; }')
        global_search.fill('Cassini')
        expect(page.locator('.vs-search-results')).to_be_visible()
        search_input_box = global_search.bounding_box()
        search_popup_box = page.locator(
            '.vs-search-results').bounding_box()
        self.assertAlmostEqual(
            search_popup_box['x'], search_input_box['x'], delta=1)
        long_result = page.locator(
            '.vs-search-result',
            has_text=(
                'Cassini Groups With A Deliberately Long Suggestion'))
        expect(long_result).to_be_visible()
        result_icon = long_result.locator('.vs-search-result-icon')
        expect(result_icon).to_be_visible()
        self.assertLess(
            result_icon.bounding_box()['x'],
            long_result.locator('.vs-search-result-name').bounding_box()['x'])
        expect(page.locator('.vs-search-result-model')).to_have_count(0)
        self.assertEqual(
            long_result.evaluate(
                'element => getComputedStyle(element).whiteSpace'),
            'nowrap')
        self.assertGreater(
            page.locator('.vs-search-results').bounding_box()['width'],
            global_search.bounding_box()['width'])
        search_results = page.locator('[data-global-search-result]')
        self.assertGreaterEqual(search_results.count(), 2)
        global_search.press('ArrowDown')
        expect(search_results.first).to_be_focused()
        page.keyboard.press('ArrowDown')
        expect(search_results.nth(1)).to_be_focused()
        page.keyboard.press('ArrowUp')
        expect(search_results.first).to_be_focused()
        page.keyboard.press('ArrowUp')
        expect(global_search).to_be_focused()
        page.get_by_role('img', name='NaN-tic').click()
        expect(page.locator('.vs-search-results')).to_have_count(0)
        global_search.fill('Cassini Gr')
        expect(page.locator('.vs-search-results')).to_be_visible()
        expect(global_search).to_be_focused()
        self.assertTrue(global_search.evaluate(
                'element => element === window.cassiniGlobalSearch'))
        with page.expect_response(
                lambda response: '/global-search' in response.url):
            page.keyboard.type('oups', delay=20)
        expect(global_search).to_have_value('Cassini Groups')
        expect(global_search).to_be_focused()
        self.assertTrue(global_search.evaluate(
                'element => element === window.cassiniGlobalSearch'))
        with page.expect_response(
                lambda response: '/open/menu/' in response.url):
            page.locator(
                '.vs-search-result',
                has_text='Cassini Groups').first.click()
        expect(page.locator('.vs-search-results')).to_have_count(0)
        expect(global_search).to_have_value('')

        page.get_by_role('button', name='User menu').click()
        logout = page.get_by_role('menuitem', name='Logout')
        expect(logout.locator(
            'img[src$="tryton-exit.svg"]')).to_be_visible()
        expect(logout).to_have_text('')
        logout.click()
        expect(page.get_by_role(
                'heading', name='Sign in')).to_be_visible()

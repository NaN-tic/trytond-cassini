from urllib.parse import urlsplit

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestURLActionsShare(WebTestCase):
    modules = ['cassini', 'babi']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionKeyword = pool.get('ir.action.keyword')
            ActionURL = pool.get('ir.action.url')
            ActionWindow = pool.get('ir.action.act_window')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            ModelData = pool.get('ir.model.data')
            Site = pool.get('www.site')
            User = pool.get('res.user')

            window, other_window = ActionWindow.create([{
                        'name': 'Cassini URL Actions',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }, {
                        'name': 'Cassini Other Window',
                        'res_model': 'res.group',
                        'domain': (
                            '[["name", "=", "CassiniShareOther"]]'),
                        'context': '{}',
                        'search_value': '[]',
                        }])
            menu_url, keyword_url = ActionURL.create([
                    {
                        'name': 'Cassini External Menu',
                        'url': '/cassini-icons/tryton-link.svg#menu-url',
                        }, {
                        'name': 'Cassini URL Keyword',
                        'url': '/cassini-icons/tryton-link.svg#keyword-url',
                        },
                    ])
            ActionKeyword.create([{
                        'keyword': 'form_relate',
                        'model': 'res.group,-1',
                        'action': keyword_url.id,
                        }])
            babi_action = pool.get('ir.action.wizard')(
                ModelData.get_id('babi', 'act_babi_open_voyager'))
            Menu.create([
                    {
                        'name': 'Cassini External Menu',
                        'action': str(menu_url),
                    }, {
                        'name': 'Cassini URL Actions',
                        'action': str(window),
                        }, {
                        'name': 'Cassini Other Window',
                        'action': str(other_window),
                    }, {
                        'name': 'Cassini BABI URL',
                        'action': str(babi_action),
                        },
                    ])
            Group.create([
                    {'name': 'CassiniShareTarget'},
                    {'name': 'CassiniShareOther'},
                    ])
            administrator = User(1)
            recipient, = User.create([{
                        'name': 'Cassini Share Recipient',
                        'login': 'cassini-share-recipient',
                        'password': cls.password,
                        'groups': [('add', [
                                    group.id
                                    for group in administrator.groups])],
                        }])
            cls.recipient = recipient.login
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            transaction.commit()

    @browser()
    def test(self, page: Page):
        console_errors = []
        page.on(
            'console',
            lambda message: console_errors.append(message.text)
            if message.type in {'error', 'warning'} else None)
        page.add_init_script('''
            Object.defineProperty(navigator, "share", {
                configurable: true,
                value: async data => { window.cassiniSharedTab = data; },
            });
        ''')
        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        page.locator('[data-panel-option="menu"]').click()

        external_menu = page.get_by_role(
            'link', name='Cassini External Menu', exact=True)
        expect(external_menu).to_have_attribute('target', '_blank')
        with page.expect_popup() as menu_popup_info:
            external_menu.click()
        menu_popup = menu_popup_info.value
        menu_popup.wait_for_load_state()
        self.assertTrue(menu_popup.url.endswith(
                '/cassini-icons/tryton-link.svg#menu-url'))
        menu_popup.close()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(0)

        with page.expect_popup() as babi_popup_info:
            page.get_by_role(
                'button', name='Cassini BABI URL', exact=True).click()
        babi_popup = babi_popup_info.value
        babi_popup.wait_for_load_state()
        self.assertIn(
            f'/{self.database}/babi/voyager', babi_popup.url)
        babi_popup.close()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(0)

        page.get_by_role(
            'button', name='Cassini Other Window', exact=True).click()
        page.get_by_role(
            'button', name='Cassini URL Actions', exact=True).click()
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(2)

        search = page.get_by_placeholder('Search', exact=True)
        search.fill('Name: =CassiniShareTarget')
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        rows = page.locator('.vs-table tbody .vs-row')
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('CassiniShareTarget')

        window_menu = page.locator('details.vs-window-menu')
        window_menu.locator('summary').click()
        window_items = window_menu.locator('[role="menuitem"]')
        expect(window_items.first).to_have_text('Share tab')
        expect(window_items.nth(1)).to_have_text('Switch view')
        share = window_items.first
        share.click()
        page.wait_for_function('window.cassiniSharedTab !== undefined')
        shared = page.evaluate('window.cassiniSharedTab')
        self.assertEqual(shared['title'], 'Cassini URL Actions')
        self.assertIn(f'/{self.database}/cassini/share/', shared['url'])
        self.assertNotEqual(shared['url'], page.url)

        anonymous_context = page.context.browser.new_context()
        anonymous_page = anonymous_context.new_page()
        anonymous_page.goto(shared['url'], wait_until='domcontentloaded')
        self.assertIn('/cassini/login/share/', anonymous_page.url)
        expect(anonymous_page.locator('input[name="next"]')).to_have_value(
            urlsplit(shared['url']).path)
        anonymous_page.locator('#username').fill(self.user)
        anonymous_page.locator('#password').fill(self.password)
        anonymous_page.get_by_role('button', name='Sign in').click()
        anonymous_page.wait_for_url(shared['url'])
        expect(anonymous_page.locator(
                '#workspace-tabs .vs-tab')).to_have_count(1)
        expect(anonymous_page.locator(
                '.vs-table tbody .vs-row')).to_have_count(1)
        anonymous_context.close()

        recipient_context = page.context.browser.new_context()
        recipient_page = recipient_context.new_page()
        recipient_page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        recipient_page.locator('#username').fill(self.recipient)
        recipient_page.locator('#password').fill(self.password)
        recipient_page.get_by_role('button', name='Sign in').click()
        recipient_page.locator('[data-panel-option="menu"]').click()
        recipient_page.get_by_role(
            'button', name='Cassini Other Window', exact=True).click()
        expect(recipient_page.locator(
                '#workspace-tabs .vs-tab')).to_have_count(1)
        recipient_page.goto(shared['url'], wait_until='domcontentloaded')
        expect(recipient_page.locator(
                '#workspace-tabs .vs-tab')).to_have_count(1)
        recipient_rows = recipient_page.locator(
            '.vs-table tbody .vs-row')
        expect(recipient_rows).to_have_count(1)
        expect(recipient_rows).to_contain_text('CassiniShareTarget')
        expect(recipient_page.get_by_text(
                'CassiniShareOther', exact=True)).to_have_count(0)
        recipient_context.close()

        relate = page.locator(
            'details.vs-action-popup[data-action-category="relate"]')
        relate.locator('summary').click()
        items = relate.locator('[role="menuitem"]')
        keyword = relate.get_by_role(
            'menuitem', name='Cassini URL Keyword', exact=True)
        expect(keyword).to_have_attribute('target', '_blank')
        expect(items.first).to_have_text('Cassini URL Keyword')
        with page.expect_popup() as keyword_popup_info:
            keyword.click()
        keyword_popup = keyword_popup_info.value
        keyword_popup.wait_for_load_state()
        self.assertTrue(keyword_popup.url.endswith(
                '/cassini-icons/tryton-link.svg#keyword-url'))
        keyword_popup.close()
        expect(page.locator('.vs-url-tab')).to_have_count(0)
        expect(page.locator('#workspace-tabs .vs-tab')).to_have_count(2)
        self.assertFalse(any(
                'Empty string passed to getElementById()' in message
                for message in console_errors))

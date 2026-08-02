from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import ServerThread, browser


class TestPersistentSession(WebTestCase):
    modules = ['cassini']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')

            group, = Group.create([{
                        'name': 'Persistent Session Group',
                        }])
            action, = ActionWindow.create([{
                        'name': 'Persistent Session',
                        'res_model': 'res.group',
                        'domain': '[["id", "=", %d]]' % group.id,
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Menu.create([{
                        'name': 'Persistent Session',
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

        cookies = {
            cookie['name']: cookie
            for cookie in page.context.cookies()
            }
        self.assertIn('tryton_session', cookies)
        self.assertNotIn('session_id', cookies)
        self.assertEqual(
            cookies['tryton_session']['path'], '/' + self.database)

        page.locator('[data-panel-option="menu"]').click()
        page.get_by_role(
            'button', name='Persistent Session', exact=True).click()
        expect(page.get_by_text(
                'Persistent Session Group', exact=True)).to_be_visible()
        expect(page.locator('.vs-tab')).to_have_count(1)

        self.server.stop()
        self.server = ServerThread(self.app)
        self.server.start()
        page.goto(
            f'{self.base_url}/{self.database}/cassini/app',
            wait_until='domcontentloaded')

        expect(page.locator('.vs-app')).to_be_visible()
        expect(page.locator('.vs-login-page')).to_have_count(0)
        expect(page.locator('.vs-tab')).to_have_count(1)
        expect(page.get_by_text(
                'Persistent Session Group', exact=True)).to_be_visible()

        cookie = next(
            cookie for cookie in page.context.cookies()
            if cookie['name'] == 'tryton_session')
        token = cookie['value'].rsplit(':', 2)[-1]
        with Transaction().start(self.database, 1) as transaction:
            Pool().get('ir.session').remove(token)
            transaction.commit()

        page.locator('[data-panel-option="menu"]').click()
        page.wait_for_url('**/cassini/login')
        expect(page.get_by_role(
                'heading', name='Sign in')).to_be_visible()
        expect(page.locator('.vs-app')).to_have_count(0)
        expect(page.locator('.vs-tab')).to_have_count(0)

        with Transaction().start(self.database, 1) as transaction:
            sao_token = Pool().get('ir.session').new({
                    'ip_address': '127.0.0.1',
                    })
            transaction.commit()
        page.context.add_cookies([{
                    'name': 'tryton_session',
                    'value': '%s:1:%s' % (self.user, sao_token),
                    'domain': 'localhost',
                    'path': '/' + self.database,
                    'httpOnly': True,
                    'secure': True,
                    'sameSite': 'Strict',
                    }])
        page.goto(
            f'{self.base_url}/{self.database}/cassini/app',
            wait_until='domcontentloaded')
        expect(page.locator('.vs-app')).to_be_visible()
        expect(page.locator('.vs-login-page')).to_have_count(0)
        self.assertNotIn(
            'session_id', {
                cookie['name'] for cookie in page.context.cookies()})

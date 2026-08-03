import base64

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestPreferencesState(WebTestCase):
    modules = ['cassini']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            Site = Pool().get('www.site')
            Group = Pool().get('res.group')
            User = Pool().get('res.user')
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            long_group, = Group.create([{
                        'name': (
                            'A deliberately very long group membership name '
                            * 12),
                        }])
            User.write([User(1)], {
                    'avatar': base64.b64decode(
                        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1'
                        'HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAA'
                        'SUVORK5CYII='),
                    'groups': [('add', [long_group.id])],
                    })
            transaction.commit()

    @browser()
    def test(self, page: Page):
        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        page.get_by_role('button', name='User menu').click()
        page.get_by_role(
            'menuitem', name='Preferences', exact=True).click()

        dialog = page.locator('.vs-preferences-dialog')
        expect(dialog).to_be_visible()
        with page.expect_navigation(wait_until='domcontentloaded'):
            with page.expect_response(
                    lambda response:
                    response.url.endswith('/preferences/save')) as saved:
                dialog.get_by_role(
                    'button', name='Save', exact=True).click()
        self.assertEqual(saved.value.status, 303)
        expect(page.locator('#preferences-title')).not_to_be_visible()
        page.get_by_role('button', name='User menu').click()
        page.get_by_role(
            'menuitem', name='Preferences', exact=True).click()
        dialog = page.locator('.vs-preferences-dialog')
        expect(dialog).to_be_visible()
        tabs = dialog.get_by_role('tab')
        expect(tabs).to_have_count(5)
        positions = tabs.evaluate_all(
            '(tabs) => tabs.map((tab) => ({'
            'x: tab.getBoundingClientRect().x, '
            'y: tab.getBoundingClientRect().y}))')
        self.assertTrue(all(
                abs(position['y'] - positions[0]['y']) < 2
                for position in positions))
        self.assertGreater(positions[1]['x'], positions[0]['x'])
        expect(dialog.locator('[role="tabpanel"]')).to_have_count(5)
        expect(dialog.locator('[role="tabpanel"]:visible')).to_have_count(1)
        expect(dialog.locator(
                '.vs-notebook > .vs-page > h3')).to_have_count(0)

        name_input = dialog.locator('[data-field="name"] input')
        email_input = dialog.locator('[data-field="email"] input')
        password_input = dialog.locator('[data-field="password"] input')
        name_box = name_input.bounding_box()
        email_box = email_input.bounding_box()
        password_box = password_input.bounding_box()
        self.assertGreater(email_box['y'], name_box['y'] + 5)
        self.assertLessEqual(abs(email_box['y'] - password_box['y']), 2)
        self.assertGreaterEqual(email_box['width'], 180)
        self.assertGreaterEqual(password_box['width'], 180)
        email_label = dialog.locator(
            'label.vs-standalone-label', has_text='Email')
        email_label_box = email_label.bounding_box()
        self.assertLessEqual(
            abs(
                email_label_box['y'] + email_label_box['height'] / 2
                - email_box['y'] - email_box['height'] / 2),
            2)

        avatar = dialog.locator('[data-field="avatar"]')
        image = avatar.locator('.vs-image-preview')
        expect(image).to_be_visible()
        self.assertGreater(
            image.evaluate('element => element.naturalWidth'), 0)
        expect(avatar.get_by_role(
            'link', name='Save as', exact=True)).to_be_visible()
        expect(avatar.get_by_role(
            'button', name='Clear', exact=True)).to_be_visible()
        expect(avatar.locator('input[type="file"]')).not_to_be_visible()

        with page.expect_response(
                lambda response:
                '/preferences/notebook/' in response.url
                and response.url.endswith('/page/2')):
            dialog.get_by_role(
                'tab', name='Group Membership', exact=True).click()
        membership = dialog.locator('[role="tabpanel"]:visible')
        long_cell = membership.locator(
            '.vs-x2many-row .vs-tree-content',
            has_text='A deliberately very long group membership name')
        expect(long_cell).to_be_visible()
        truncation = long_cell.evaluate(
            '''element => {
                const style = getComputedStyle(element);
                return {
                    clientWidth: element.clientWidth,
                    scrollWidth: element.scrollWidth,
                    textOverflow: style.textOverflow,
                    whiteSpace: style.whiteSpace,
                };
            }''')
        self.assertGreater(
            truncation['scrollWidth'], truncation['clientWidth'])
        self.assertEqual(truncation['textOverflow'], 'ellipsis')
        self.assertEqual(truncation['whiteSpace'], 'nowrap')

        table = membership.locator('.vs-x2many-table')
        resizer = table.locator('[data-column-resizer]').first
        expect(resizer).to_have_css('opacity', '0')
        table.locator('thead').hover()
        expect(resizer).to_have_css('opacity', '1')
        self.assertEqual(resizer.evaluate(
            '''element => getComputedStyle(element, '::after').width'''),
            '2px')
        column = table.locator(
            'col[data-column-field]').first
        old_width = column.evaluate(
            'element => element.getBoundingClientRect().width')
        with page.expect_response(
                lambda response:
                response.url.endswith('/tree/columns/width')
                and response.request.method == 'POST'):
            resizer.press('ArrowRight')
        resized_width = column.evaluate(
            'element => element.getBoundingClientRect().width')
        self.assertGreater(resized_width, old_width + 10)
        page.reload(wait_until='domcontentloaded')
        dialog = page.locator('.vs-preferences-dialog')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role(
            'tab', name='Group Membership',
            exact=True)).to_have_attribute('aria-selected', 'true')
        persisted_width = dialog.locator(
            '[role="tabpanel"]:visible '
            '.vs-x2many-table col[data-column-field]').first.evaluate(
                'element => element.getBoundingClientRect().width')
        self.assertLessEqual(abs(persisted_width - resized_width), 3)

        with page.expect_response(
                lambda response:
                '/preferences/notebook/' in response.url
                and response.url.endswith('/page/4')):
            dialog.get_by_role(
                'tab', name='Preferences', exact=True).click()
        expect(dialog.get_by_role(
                'tab', name='Preferences', exact=True)).to_have_attribute(
                    'aria-selected', 'true')
        expect(dialog.locator('[role="tabpanel"]:visible')).to_have_count(1)
        expect(dialog.locator('[role="tabpanel"]:visible')).to_contain_text(
            'Language')

        email = page.locator('[data-field="email"] input')
        email.press('Control+A')
        with page.expect_response(
                lambda response: '/preferences/field/email' in response.url):
            email.press_sequentially('draft@example.test')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#preferences-title')).to_be_visible()
        expect(page.get_by_role(
                'tab', name='Preferences', exact=True)).to_have_attribute(
                    'aria-selected', 'true')
        expect(page.locator(
                '.vs-preferences-dialog '
                '[role="tabpanel"]:visible')).to_contain_text('Language')
        expect(page.locator(
                '[data-field="email"] input')).to_have_value(
                    'draft@example.test')
        page.get_by_role('button', name='Cancel').click()
        expect(page.locator('#preferences-title')).not_to_be_visible()

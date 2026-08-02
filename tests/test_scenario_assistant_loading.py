import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from playwright.sync_api import Page, expect
from trytond import __version__ as tryton_version
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestAssistantLoading(WebTestCase):
    modules = ['cassini', 'nantic_connection']
    timeout = 10000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWizard = pool.get('ir.action.wizard')
            ActionWindow = pool.get('ir.action.act_window')
            Conversation = pool.get('nantic.chat.conversation')
            Menu = pool.get('ir.ui.menu')
            Notification = pool.get('res.notification')
            Update = pool.get('nantic_connection.notification')
            UpdateWizard = pool.get(
                'nantic_connection.notification.wizard')
            Site = pool.get('www.site')
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            conversation = Conversation(
                identifier='12345678-1234-1234-1234-123456789012',
                title='Markdown conversation')
            conversation.save()
            conversation.add_message(SimpleNamespace(
                    content=(
                        '**Assistant answer**\n\n'
                        '- First item\n'
                        '- Second item'),
                    tool_calls=None), 'assistant')
            action, = ActionWindow.create([{
                        'name': 'Open assistant conversation',
                        'res_model': 'nantic.chat.conversation',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            Notification.create([{
                        'user': 1,
                        'label': 'Open markdown conversation',
                        'description': 'Open the assistant directly',
                        'icon': 'tryton-goblin',
                        'action': action.id,
                        'action_value': json.dumps(
                        conversation.get_open_action()),
                        }])
            wizard, = ActionWizard.create([{
                        'name': 'Cassini Help Wizard',
                        'wiz_name': 'www.uri.builder',
                        }])
            update = Update(
                datetime=datetime.now() + timedelta(minutes=2),
                subject_en='Wizard contextual update',
                subject_ca='Actualització contextual del wizard',
                subject_es='Actualización contextual del wizard',
                description_en='Contextual wizard documentation.',
                description_ca='Documentació contextual del wizard.',
                description_es='Documentación contextual del wizard.',
                severity='low')
            update.save()
            UpdateWizard.create([{
                        'notification': update.id,
                        'name': 'www.uri.builder',
                        }])
            version = '.'.join(tryton_version.split('.')[:2])
            version_update = Update(
                datetime=datetime.now() + timedelta(minutes=1),
                subject_en='Cassini version changes',
                subject_ca='Canvis de versió de Cassini',
                subject_es='Cambios de versión de Cassini',
                description_en=(
                    '## Version changes\n\n- First improvement\n- Second improvement'),
                description_ca=(
                    '## Canvis de versió\n\n- Primera millora\n- Segona millora'),
                description_es=(
                    '## Cambios de versión\n\n- Primera mejora\n- Segunda mejora'),
                version=version,
                severity='version_change')
            version_update.save()
            Menu.create([{
                        'name': 'Cassini Help Wizard',
                        'action': str(wizard),
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

        version_dialog = page.locator('.vs-version-changes-dialog')
        expect(version_dialog).to_be_visible()
        self.assertGreaterEqual(version_dialog.bounding_box()['width'], 700)
        expect(version_dialog.locator('li')).to_have_count(2)
        expect(version_dialog.get_by_role(
            'button', name="Don't show again")).to_be_visible()
        version_dialog.get_by_role(
            'button', name="Don't show again").click()
        expect(version_dialog).not_to_be_visible()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.vs-version-changes-dialog')).to_have_count(0)

        panel_controls = page.get_by_role(
            'navigation', name='Side panel')
        expect(panel_controls.get_by_role(
            'button', name='No side panel')).to_be_visible()
        expect(panel_controls.get_by_role(
            'button', name='Menu', exact=True)).to_be_visible()
        expect(panel_controls.get_by_role(
            'button', name='Help', exact=True)).to_be_visible()
        global_search = page.get_by_label('Global search')
        logo = page.get_by_role('img', name='NaN-tic')
        expect(logo).to_be_visible()
        self.assertGreater(
            logo.evaluate('element => element.naturalWidth'), 0)
        favorites = page.locator(
            '.vs-global-favorites-toggle[aria-label="Favorites"]')
        expect(favorites).to_be_visible()
        self.assertLessEqual(
            abs(
                favorites.bounding_box()['x']
                + favorites.bounding_box()['width']
                - global_search.bounding_box()['x']),
            1)
        favorites.click()
        expect(page.get_by_role(
            'menu', name='Favorites')).to_be_visible()
        expect(page.get_by_text(
            'No favorites yet', exact=True)).to_be_visible()
        favorites.click()

        global_message = 'Open the assistant from global search'
        global_search.fill(global_message)
        with page.expect_response(
                lambda response: response.url.endswith('/help/chat')):
            global_search.press('Enter')
        expect(page.locator('#help-sidebar')).to_be_visible()
        expect(page.get_by_role(
            'button', name='Assistant',
            exact=True)).to_have_attribute('aria-expanded', 'true')
        help_icons = page.locator(
            '#help-panel img[src^="/cassini-help-icons/"]')
        self.assertGreaterEqual(help_icons.count(), 10)
        self.assertTrue(help_icons.evaluate_all(
            '''icons => icons.every(icon =>
                icon.complete && icon.naturalWidth > 0
                && icon.getBoundingClientRect().width > 0
                && icon.getBoundingClientRect().height > 0)'''))
        expect(page.locator(
            '.vs-chat-message.vs-chat-user',
            has_text=global_message)).to_be_visible()
        expect(page.get_by_label('Global search')).to_have_value('')
        panel_controls.get_by_role(
            'button', name='No side panel').click()

        expect(page.locator('.vs-hint-menu')).to_be_visible()
        expect(page.locator('.vs-hint-help')).to_be_visible()
        expect(page.locator('.vs-hint-favorites')).to_be_visible()
        panel_controls.get_by_role(
            'button', name='Menu', exact=True).click()
        expect(page.locator('.vs-hint-menu')).to_have_count(0)
        expect(page.locator('.vs-hint-help')).to_have_count(0)
        expect(page.locator('.vs-hint-favorites')).to_have_count(0)
        resize_hint = page.locator('.vs-hint-resize')
        expect(resize_hint).to_be_visible()
        self.assertLessEqual(
            abs(
                resize_hint.bounding_box()['y']
                + resize_hint.bounding_box()['height']
                - page.locator('.vs-welcome').bounding_box()['y']
                - page.locator('.vs-welcome').bounding_box()['height']),
            1)
        self.assertLessEqual(
            abs(
                resize_hint.bounding_box()['y']
                + resize_hint.bounding_box()['height']
                - page.viewport_size['height']),
            1)
        panel_controls.get_by_role(
            'button', name='No side panel').click()
        expect(page.locator('.vs-hint-menu')).to_be_visible()
        expect(page.locator('.vs-hint-resize')).to_have_count(0)

        page.get_by_role('button', name='User menu').click()
        notification = page.locator(
            '.vs-notification-item',
            has_text='Open markdown conversation').get_by_role(
                'menuitem')
        expect(notification).to_be_visible()
        expect(notification.locator(
            'img[src="/cassini-help-icons/goblin.svg"]')).to_be_visible()
        with page.expect_response(
                lambda response: '/notification/' in response.url):
            notification.click()
        expect(page.locator('#help-sidebar')).to_be_visible()
        expect(page.get_by_role(
            'button', name='Assistant',
            exact=True)).to_have_attribute('aria-expanded', 'true')

        assistant = page.locator(
            '.vs-chat-message.vs-chat-assistant')
        expect(assistant).to_be_visible()
        expect(page.locator('.vs-chat-author')).to_have_count(0)
        self.assertEqual(
            assistant.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            'rgba(0, 0, 0, 0)')
        items = assistant.locator('ul > li')
        expect(items).to_have_count(2)
        self.assertEqual(
            items.first.evaluate(
                'element => getComputedStyle(element).listStyleType'),
            'disc')

        new_conversation = page.get_by_role(
            'button', name='New conversation')
        nan_toggle = page.get_by_role(
            'button', name='Choose a NaN')
        self.assertLessEqual(
            abs(
                new_conversation.bounding_box()['x']
                + new_conversation.bounding_box()['width']
                - nan_toggle.bounding_box()['x']),
            1)
        nan_toggle.click()
        expect(page.get_by_role(
            'menuitem', name='Default')).to_be_visible()
        nan_toggle.click()

        with page.expect_response(
                lambda response: '/help/resource/agents' in response.url):
            page.get_by_role(
                'button', name='NaNs and goblins').click()
        expect(page.locator(
            '.vs-tab', has_text='NaNs and goblins')).to_be_visible()

        page.get_by_label('Message').fill('Show the loading indicator')
        with page.expect_response(
                lambda response: '/help/chat' in response.url):
            page.get_by_label('Message').press('Enter')

        indicator = page.get_by_role(
            'status', name='Assistant is working')
        expect(indicator).to_be_visible()
        expect(indicator).to_have_text('')
        style = indicator.evaluate(
            '''element => {
                const style = getComputedStyle(element);
                return {
                    animationDirection: style.animationDirection,
                    animationDuration: style.animationDuration,
                    animationName: style.animationName,
                    borderRadius: style.borderRadius,
                    width: style.width,
                };
            }''')
        self.assertEqual(style, {
                'animationDirection': 'alternate',
                'animationDuration': '0.5s',
                'animationName': 'vs-loading-assistant',
                'borderRadius': '100px',
                'width': '30px',
                })
        expect(page.get_by_text('Working…', exact=True)).to_have_count(0)
        expect(page.get_by_label('Message')).to_have_value('')
        user_message = page.locator(
            '.vs-chat-message.vs-chat-user',
            has_text='Show the loading indicator')
        expect(user_message).to_be_visible()
        self.assertNotEqual(
            user_message.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            'rgba(0, 0, 0, 0)')

        panel_controls.get_by_role(
            'button', name='Menu', exact=True).click()
        page.get_by_role(
            'button', name='Cassini Help Wizard', exact=True).click()
        wizard_dialog = page.get_by_role(
            'dialog', name='Cassini Help Wizard')
        expect(wizard_dialog).to_be_visible()
        wizard_help = wizard_dialog.get_by_role(
            'button', name='Help', exact=True)
        expect(wizard_help).to_be_visible()
        wizard_help.click()
        wizard_dialog = page.get_by_role(
            'dialog', name='Cassini Help Wizard')
        expect(wizard_dialog.locator('.vs-wizard-help')).to_be_visible()
        expect(wizard_dialog.get_by_role(
            'button', name='Help', exact=True)).to_have_attribute(
                'aria-pressed', 'true')
        contextual_update = wizard_dialog.locator(
            '.vs-help-update', has_text='Wizard contextual update')
        expect(contextual_update).to_be_visible()
        contextual_update.click()
        wizard_dialog = page.get_by_role(
            'dialog', name='Cassini Help Wizard')
        expect(wizard_dialog.get_by_text(
            'Contextual wizard documentation.', exact=True)).to_be_visible()
        with page.expect_response(
                lambda response: '/wizard/help/back' in response.url):
            wizard_dialog.get_by_role(
                'button', name='Back', exact=True).click()
        wizard_dialog = page.get_by_role(
            'dialog', name='Cassini Help Wizard')
        with page.expect_response(
                lambda response: '/wizard/help/filter' in response.url):
            wizard_dialog.get_by_role(
                'button', name='All updates', exact=True).click()
        expect(page.get_by_role(
            'dialog', name='Cassini Help Wizard').locator(
                '.vs-wizard-help')).to_be_visible()
        page.get_by_role(
            'dialog', name='Cassini Help Wizard').get_by_role(
                'button', name='Cancel', exact=True).click()
        expect(page.locator('.vs-wizard')).not_to_be_visible()

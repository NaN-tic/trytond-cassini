from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestShellDemo(WebTestCase):
    modules = ['cassini']
    timeout = 15000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowDomain = pool.get('ir.action.act_window.domain')
            ActionWindowView = pool.get('ir.action.act_window.view')
            Group = pool.get('res.group')
            Menu = pool.get('ir.ui.menu')
            Notification = pool.get('res.notification')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')

            view, = View.create([{
                        'model': 'res.group',
                        'type': 'tree',
                        'data': (
                            '<tree>'
                            '<field name="name"/>'
                            '<field name="active" optional="1"/>'
                            '</tree>'),
                        }])
            action, = ActionWindow.create([{
                        'name': 'Shell Groups',
                        'res_model': 'res.group',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': action.id,
                        }])
            ActionWindowDomain.create([
                    {
                        'name': 'All groups',
                        'domain': '[]',
                        'count': True,
                        'act_window': action.id,
                        },
                    {
                        'name': 'Only active',
                        'domain': '[["active", "=", true]]',
                        'count': True,
                        'act_window': action.id,
                        },
                    {
                        'name': 'Without counter',
                        'domain': '[]',
                        'count': False,
                        'act_window': action.id,
                        },
                    ])
            section, = Menu.create([{
                        'name': 'Shell Tests',
                        'icon': 'tryton-menu',
                        }])
            Menu.create([{
                        'name': 'Shell Groups',
                        'icon': 'tryton-open',
                        'action': str(action),
                        'parent': section.id,
                        }])
            dynamic_selection_view, = View.create([{
                        'model': 'res.notification',
                        'type': 'tree',
                        'data': (
                            '<tree>'
                            '<field name="icon"/>'
                            '<field name="label"/>'
                            '</tree>'),
                        }])
            dynamic_selection_action, = ActionWindow.create([{
                        'name': 'Dynamic Selections',
                        'res_model': 'res.notification',
                        'domain': '[]',
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': dynamic_selection_view.id,
                        'act_window': dynamic_selection_action.id,
                        }])
            Menu.create([{
                        'name': 'Dynamic Selections',
                        'action': str(dynamic_selection_action),
                        'parent': section.id,
                        }])
            groups = Group.create([
                    {'name': 'Shell Group Alpha'},
                    {'name': 'Shell Group Beta'},
                    ])
            cls.alpha_id = groups[0].id
            cls.group_count = Group.search_count([])
            cls.active_group_count = Group.search_count([
                    ('active', '=', True)])
            Group.fields_view_get(
                view_id=view.id, view_type='tree')
            Group.view_toolbar_get()
            Notification.fields_view_get(
                view_id=dynamic_selection_view.id, view_type='tree')
            Notification.view_toolbar_get()
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

        expect(page.locator('#main-menu')).to_have_count(0)
        expect(page.locator('#help-sidebar')).to_have_count(0)
        panel_controls = page.get_by_role(
            'navigation', name='Side panel')
        menu_panel = panel_controls.get_by_role(
            'button', name='Menu', exact=True)
        expect(menu_panel).to_have_attribute('aria-pressed', 'false')
        expect(panel_controls.get_by_role(
            'button', name='No side panel')).to_have_count(0)
        expect(panel_controls.get_by_role(
            'button', name='Help', exact=True)).to_have_count(0)
        expect(panel_controls.locator('.vs-icon')).to_have_count(1)
        global_search = page.get_by_label('Global search')
        expect(global_search).to_have_attribute(
            'placeholder', 'Search 🔍︎')
        logo = page.get_by_role('img', name='NaN-tic')
        expect(logo).to_be_visible()
        expect(logo).to_have_attribute('data-seasonal-logo', 'true')
        self.assertGreater(
            logo.evaluate('element => element.naturalWidth'), 0)
        header_box = page.locator('.vs-header').bounding_box()
        self.assertEqual(header_box['height'], 50)
        menu_button_box = menu_panel.bounding_box()
        self.assertEqual(menu_button_box['width'], 42)
        self.assertEqual(menu_button_box['height'], 42)
        logo_margins = logo.evaluate(
            '''element => ({
                left: getComputedStyle(element).marginLeft,
                right: getComputedStyle(element).marginRight,
            })''')
        self.assertEqual(logo_margins, {'left': '10px', 'right': '10px'})
        self.assertGreater(
            global_search.bounding_box()['x'],
            logo.bounding_box()['x'] + logo.bounding_box()['width'])
        self.assertGreater(
            logo.bounding_box()['x'],
            menu_panel.bounding_box()['x'])
        expect(page.get_by_role(
            'heading', name='What do you want to do?')).to_be_visible()
        welcome_search = page.locator('[data-welcome-search]')
        expect(welcome_search).to_have_attribute(
            'placeholder', 'Search 🔍︎')
        expect(page.locator('.vs-hint-menu')).to_be_visible()
        self.assertEqual(
            page.locator('.vs-active-panel-empty').evaluate(
                'element => getComputedStyle(element).borderTopWidth'),
            '0px')
        global_search_handle = global_search.element_handle()
        with page.expect_response(
                lambda response: response.url.endswith(
                    '/global-search/results')):
            welcome_search.press_sequentially('Shell', delay=8)
        self.assertTrue(global_search_handle.evaluate(
            'element => element.isConnected'))
        expect(global_search).to_have_value('Shell')
        expect(global_search).to_be_focused()
        global_search.fill('')

        menu_panel.click()
        expect(page.locator('#main-menu')).to_be_visible()
        menu_sidebar = page.locator('#main-menu')
        self.assertEqual(
            menu_sidebar.evaluate(
                'element => getComputedStyle(element).resize'),
            'horizontal')
        menu_width = menu_sidebar.bounding_box()['width']
        with page.expect_response(
                lambda response: response.url.endswith('/shell/width')):
            menu_sidebar.evaluate(
                'element => element.style.width = "24rem"')
        resized_menu_width = menu_sidebar.bounding_box()['width']
        self.assertGreater(
            resized_menu_width, menu_width)
        menu_bottom = menu_sidebar.evaluate(
            'element => element.getBoundingClientRect().bottom')
        viewport_bottom = page.evaluate('window.innerHeight')
        self.assertLessEqual(abs(menu_bottom - viewport_bottom), 1)
        expect(menu_panel).to_have_attribute('aria-pressed', 'true')
        page.reload(wait_until='domcontentloaded')
        expect(menu_sidebar).to_be_visible()
        self.assertLessEqual(
            abs(menu_sidebar.bounding_box()['width'] - resized_menu_width), 1)
        menu_panel.click()
        expect(page.locator('#main-menu')).to_have_count(0)
        expect(menu_panel).to_have_attribute('aria-pressed', 'false')
        menu_panel.click()
        expect(menu_sidebar).to_be_visible()
        self.assertLessEqual(
            abs(menu_sidebar.bounding_box()['width'] - resized_menu_width), 1)
        menu_panel.click()
        expect(page.locator('#main-menu')).to_have_count(0)
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#main-menu')).to_have_count(0)
        expect(page.locator('#help-sidebar')).to_have_count(0)
        expect(menu_panel).to_have_attribute('aria-pressed', 'false')

        page.get_by_role('button', name='User menu').click()
        page.get_by_role(
            'menuitem', name='Switch light/dark mode').click()
        expect(page.locator('html')).to_have_attribute(
            'data-theme', 'dark')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('html')).to_have_attribute(
            'data-theme', 'dark')

        page.get_by_role('button', name='User menu').click()
        expect(page.locator('.vs-brand-title')).to_have_count(0)
        expect(page.get_by_role(
            'menuitem', name='Help')).to_have_count(0)
        page.get_by_role('menuitem', name='Demo').click()
        expect(page.get_by_text(
                'This page uses no Tryton XML view')).to_be_visible()
        title = page.locator('#demo-title')
        with page.expect_response(
                lambda response: '/demo/title' in response.url):
            title.fill('Unfinished custom interface')
        expect(page.locator('#demo-title')).to_have_value(
            'Unfinished custom interface')
        page.get_by_role('button', name='increment').click()
        expect(page.locator('.vs-demo-counter')).to_have_text('1')
        with page.expect_response(
                lambda response: '/demo/task-draft' in response.url):
            task_input = page.get_by_placeholder('A new task')
            task_input.evaluate(
                'element => window.cassiniTaskInput = element')
            task_input.press_sequentially(
                'Persistent task written quickly', delay=8)
        expect(task_input).to_have_value(
            'Persistent task written quickly')
        self.assertTrue(task_input.evaluate(
            'element => element === window.cassiniTaskInput'))
        expect(task_input).to_be_focused()
        with page.expect_response(
                lambda response: '/demo/add' in response.url):
            page.get_by_role('button', name='Add').click()
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#demo-title')).to_have_value(
            'Unfinished custom interface')
        expect(page.locator('.vs-demo-counter')).to_have_text('1')
        expect(page.get_by_text(
                'Persistent task written quickly',
                exact=True)).to_be_visible()

        page.get_by_role('link', name='Back to Sao').click()
        page.locator('[data-panel-option="menu"]').click()
        expect(page.get_by_role(
                'button', name='Shell Groups', exact=True)).to_have_count(0)
        page.get_by_role(
            'button', name='Shell Tests', exact=True).click()
        expect(page.get_by_role(
                'button', name='Shell Groups', exact=True)).to_be_visible()
        expect(page.get_by_role(
            'button', name='Shell Groups', exact=True).locator(
                '.vs-menu-item-icon')).to_be_visible()
        menu_geometry = page.get_by_role(
            'button', name='Shell Groups', exact=True).evaluate(
                '''button => {
                    const icon = button.querySelector(
                        '.vs-menu-item-icon').getBoundingClientRect();
                    const text = button.querySelector(
                        '.vs-menu-item-label > span').getBoundingClientRect();
                    return {
                        iconCenter: icon.y + icon.height / 2,
                        textCenter: text.y + text.height / 2,
                        iconRight: icon.right,
                        textLeft: text.left,
                    };
                }''')
        self.assertLessEqual(abs(
            menu_geometry['iconCenter']
            - menu_geometry['textCenter']), 1)
        self.assertLess(
            menu_geometry['iconRight'], menu_geometry['textLeft'])
        page.get_by_role(
            'button', name='Add Shell Groups to favorites').click()
        expect(page.get_by_role(
            'button', name='Remove Shell Groups from favorites')).to_be_visible()
        page.get_by_role(
            'button', name='Add Dynamic Selections to favorites').click()
        expect(page.get_by_role(
            'button',
            name='Remove Dynamic Selections from favorites')).to_be_visible()
        global_favorites = page.locator(
            '.vs-global-favorites-toggle[aria-label="Favorites"]')
        global_favorites.click()
        expect(page.get_by_role(
            'menuitem',
            name='Shell Tests / Shell Groups',
            exact=True)).to_be_visible()
        global_favorites.click()
        expect(page.locator(
            '.vs-welcome-favorite',
            has_text='Shell Groups')).to_be_visible()
        welcome_favorites = page.locator('.vs-welcome-favorites')
        expect(welcome_favorites.locator(
            '.vs-welcome-favorite')).to_have_count(2)
        favorite_geometry = welcome_favorites.evaluate(
            '''element => {
                const center = element.closest('.vs-welcome-center');
                const box = element.getBoundingClientRect();
                const centerBox = center.getBoundingClientRect();
                const buttons = Array.from(element.querySelectorAll(
                    '.vs-welcome-favorite'));
                return {
                    blockCenter: box.x + box.width / 2,
                    center: centerBox.x + centerBox.width / 2,
                    lefts: buttons.map(button =>
                        button.getBoundingClientRect().x),
                    textAlign: buttons.map(button =>
                        getComputedStyle(button).textAlign),
                    width: box.width,
                };
            }''')
        self.assertLessEqual(abs(
            favorite_geometry['blockCenter']
            - favorite_geometry['center']), 1)
        self.assertLessEqual(abs(
            favorite_geometry['lefts'][0]
            - favorite_geometry['lefts'][1]), 1)
        self.assertEqual(
            favorite_geometry['textAlign'], ['left', 'left'])
        self.assertLess(favorite_geometry['width'], 400)
        menu_child = page.get_by_role(
            'button', name='Shell Groups', exact=True).locator(
                'xpath=ancestor::li[1]')
        menu_parent = page.get_by_text(
            'Shell Tests', exact=True).locator('xpath=ancestor::li[1]')
        expect(menu_child.locator(
            ':scope > .vs-hierarchy-row')).to_have_count(1)
        self.assertGreater(
            menu_child.locator(
                ':scope > .vs-hierarchy-row').bounding_box()['x'],
            menu_parent.locator(
                ':scope > .vs-hierarchy-row').bounding_box()['x'])
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_role(
                'button', name='Shell Groups', exact=True)).to_be_visible()
        with page.expect_response(
                lambda response: '/open/menu/' in response.url) as opened:
            page.get_by_role(
                'button', name='Shell Groups', exact=True).click()
        open_ms = float(
            opened.value.headers['x-cassini-ms'])
        self.assertLess(
            open_ms, 75,
            'A cached window action took %.3f ms' % open_ms)
        tabs = page.locator('#workspace-tabs .vs-tab')
        expect(tabs).to_have_count(1)
        close_tab = page.locator('.vs-tab-close')
        self.assertAlmostEqual(
            float(close_tab.evaluate(
                'element => parseFloat(getComputedStyle(element).fontSize)')),
            27.6, places=1)
        domain_tabs = page.get_by_role(
            'navigation', name='Domains')
        all_groups = domain_tabs.get_by_role(
            'tab', name='All groups', exact=True)
        only_active = domain_tabs.get_by_role(
            'tab', name='Only active', exact=True)
        without_counter = domain_tabs.get_by_role(
            'tab', name='Without counter', exact=True)
        expect(all_groups).to_have_attribute('aria-selected', 'true')
        expect(only_active).to_have_attribute('aria-selected', 'false')
        expect(without_counter).to_have_attribute(
            'aria-selected', 'false')
        expect(domain_tabs.get_by_role('tab')).to_have_count(3)
        domain_counts = domain_tabs.locator('.vs-domain-count')
        expect(domain_counts).to_have_count(2)
        expect(domain_counts.nth(0)).to_have_text(str(self.group_count))
        expect(domain_counts.nth(1)).to_have_text(
            str(self.active_group_count))
        only_active.click()
        expect(only_active).to_have_attribute('aria-selected', 'true')
        domain_geometry = domain_tabs.evaluate(
            '''element => {
                const active = element.querySelector(
                    '.vs-local-tab-active');
                const button = active.querySelector(
                    '.vs-local-tab-title');
                const activeBox = active.getBoundingClientRect();
                const navBox = element.getBoundingClientRect();
                const toolbar = element.closest('.vs-toolbar');
                const toolbarBox = toolbar.getBoundingClientRect();
                const contentBox = toolbar.nextElementSibling
                    .getBoundingClientRect();
                const navStyle = getComputedStyle(element);
                const activeStyle = getComputedStyle(active);
                const buttonStyle = getComputedStyle(button);
                return {
                    activeBottom: activeBox.bottom,
                    contentTop: contentBox.top,
                    navBorderBottom: navStyle.borderBottomWidth,
                    navBackground: navStyle.backgroundColor,
                    navBottom: navBox.bottom,
                    navRight: navBox.right,
                    navOverflowY: navStyle.overflowY,
                    activeBorderLeft: activeStyle.borderLeftWidth,
                    activeBorderRight: activeStyle.borderRightWidth,
                    activeBorderBottom: activeStyle.borderBottomWidth,
                    buttonBorderLeft: buttonStyle.borderLeftWidth,
                    toolbarRight: toolbarBox.right,
                };
            }''')
        self.assertEqual(domain_geometry['navBorderBottom'], '1px')
        self.assertEqual(domain_geometry['navBackground'], 'rgb(23, 33, 31)')
        self.assertEqual(domain_geometry['navOverflowY'], 'hidden')
        self.assertEqual(domain_geometry['activeBorderLeft'], '1px')
        self.assertEqual(domain_geometry['activeBorderRight'], '1px')
        self.assertEqual(domain_geometry['activeBorderBottom'], '0px')
        self.assertEqual(domain_geometry['buttonBorderLeft'], '0px')
        self.assertLessEqual(abs(
            domain_geometry['activeBottom']
            - domain_geometry['navBottom']), 1)
        self.assertLessEqual(abs(
            domain_geometry['contentTop']
            - domain_geometry['navBottom']), 1)
        self.assertLessEqual(abs(
            domain_geometry['navRight']
            - domain_geometry['toolbarRight']), 1)
        page.locator('#main-menu').get_by_role(
            'button', name='Dynamic Selections', exact=True).click()
        expect(tabs).to_have_count(2)
        expect(page.locator(
            '#workspace-tabs .vs-tab-active .vs-tab-title')).to_have_text(
                'Shell Tests / Dynamic Selections')
        page.locator('#main-menu').get_by_role(
            'button', name='Shell Groups', exact=True).click()
        expect(tabs).to_have_count(2)
        expect(page.locator(
            '#workspace-tabs .vs-tab-active .vs-tab-title')).to_have_text(
                'Shell Tests / Shell Groups')
        expect(page.get_by_role(
            'tab', name='Only active', exact=True)).to_have_attribute(
                'aria-selected', 'true')
        connected_tabs = page.evaluate(
            '''() => {
                const header = document.querySelector('.vs-header');
                const tab = document.querySelector(
                    '#workspace-tabs .vs-tab-active');
                const panel = document.querySelector('.vs-active-panel');
                const headerBox = header.getBoundingClientRect();
                const tabBox = tab.getBoundingClientRect();
                const panelBox = panel.getBoundingClientRect();
                const tabStyle = getComputedStyle(tab);
                return {
                    headerBottom: headerBox.bottom,
                    panelTop: panelBox.top,
                    tabBottom: tabBox.bottom,
                    tabBorderBottom: tabStyle.borderBottomWidth,
                    tabBorderLeft: tabStyle.borderLeftWidth,
                    tabBorderRight: tabStyle.borderRightWidth,
                };
            }''')
        self.assertLessEqual(abs(
            connected_tabs['tabBottom']
            - connected_tabs['headerBottom']), 1)
        self.assertLessEqual(abs(
            connected_tabs['panelTop']
            - connected_tabs['headerBottom']), 1)
        self.assertEqual(connected_tabs['tabBorderBottom'], '0px')
        self.assertEqual(connected_tabs['tabBorderLeft'], '1px')
        self.assertEqual(connected_tabs['tabBorderRight'], '1px')
        main = page.locator('.vs-main')
        main.evaluate(
            '''element => {
                const spacer = document.createElement('div');
                spacer.id = 'sticky-test-spacer';
                spacer.style.height = '80rem';
                element.querySelector('.vs-screen').append(spacer);
                element.scrollTop = 300;
            }''')
        page.wait_for_function(
            '''() => {
                const toolbar = document.querySelector('.vs-toolbar');
                const main = document.querySelector('.vs-main');
                return Math.abs(
                    toolbar.getBoundingClientRect().top
                    - main.getBoundingClientRect().top) <= 1;
            }''')
        tabs_box = page.locator('#workspace-tabs').bounding_box()
        global_box = page.locator('#global-search').bounding_box()
        user_box = page.locator('.vs-user-nav').bounding_box()
        header_geometry = page.evaluate("""
            () => ({
                viewport: [window.innerWidth, window.innerHeight],
                tabsParent: document.querySelector(
                    '#workspace-tabs').parentElement.className,
                children: Array.from(document.querySelector(
                    '.vs-header').children).map(element => ({
                        className: element.className,
                        rect: element.getBoundingClientRect().toJSON(),
                    })),
            })
            """)
        toolbar = page.locator('.vs-toolbar')
        toolbar_box = toolbar.bounding_box()
        main_box = main.bounding_box()
        sticky_geometry = page.locator('.vs-workspace').evaluate(
            '''element => {
                const tabs = document.querySelector('#workspace-tabs');
                const toolbar = element.querySelector('.vs-toolbar');
                return {
                    mainScroll: element.closest('.vs-main').scrollTop,
                    tabsHeight: tabs.getBoundingClientRect().height,
                    tabsTop: tabs.getBoundingClientRect().top,
                    toolbarTop: getComputedStyle(toolbar).top,
                    toolbarY: toolbar.getBoundingClientRect().top,
                    screenTop: element.querySelector(
                        '.vs-screen').getBoundingClientRect().top,
                    screenBottom: element.querySelector(
                        '.vs-screen').getBoundingClientRect().bottom,
                    mainTop: element.closest(
                        '.vs-main').getBoundingClientRect().top,
                    workspaceTop: element.getBoundingClientRect().top,
                    panelTop: element.querySelector(
                        '.vs-active-panel').getBoundingClientRect().top,
                };
            }''')
        self.assertEqual(
            header_geometry['tabsParent'], 'vs-header',
            header_geometry)
        self.assertLess(
            global_box['x'], tabs_box['x'], header_geometry)
        self.assertLess(
            tabs_box['x'], user_box['x'], header_geometry)
        self.assertLessEqual(
            abs(toolbar_box['y'] - main_box['y']), 1,
            sticky_geometry)
        self.assertNotEqual(
            page.locator('.vs-header').evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            'rgba(0, 0, 0, 0)')
        self.assertNotEqual(
            toolbar.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            'rgba(0, 0, 0, 0)')
        main.evaluate(
            '''element => {
                element.querySelector('#sticky-test-spacer').remove();
                element.scrollTop = 0;
            }''')
        table = page.locator('.vs-table')
        self.assertLess(
            toolbar.bounding_box()['y'],
            table.bounding_box()['y'])
        titles = toolbar.locator('[title]').evaluate_all(
            '(nodes) => nodes.map((node) => node.title)')
        positions = [
            titles.index(title)
            for title in (
                'New', 'Save', 'Reload/Undo')
            ]
        self.assertEqual(positions, sorted(positions))
        new_button = toolbar.get_by_role(
            'button', name='New', exact=True)
        save_button = toolbar.get_by_role(
            'button', name='Save', exact=True)
        inactive_button = toolbar.get_by_role(
            'button', name='Show inactive records', exact=True)
        regular_background = new_button.evaluate(
            'element => getComputedStyle(element).backgroundColor')
        self.assertEqual(
            save_button.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            regular_background)
        self.assertEqual(
            inactive_button.evaluate(
                'element => getComputedStyle(element).backgroundColor'),
            regular_background)
        self.assertNotIn('Duplicate', titles)
        self.assertNotIn('Delete', titles)
        expect(toolbar.locator('.vs-window-title')).to_have_attribute(
            'aria-label', 'Window actions: Shell Tests / Shell Groups')
        expect(toolbar.locator('.vs-window-heading-label')).to_have_text(
            'Shell Tests / Shell Groups')
        toolbar.locator('.vs-window-title').click()
        expect(toolbar.locator('.vs-window-menu-list').get_by_role(
            'menuitem').first).to_have_text('Switch view')
        toolbar.locator('.vs-window-title').click()
        expect(toolbar.locator(
            '.vs-window-title-caret')).to_have_css(
                'border-left-style', 'solid')
        toolbar_actions_box = toolbar.locator(
            '.vs-toolbar-actions').bounding_box()
        self.assertLessEqual(
            abs(
                toolbar_actions_box['x'] + toolbar_actions_box['width']
                - (
                    toolbar.bounding_box()['x']
                    + toolbar.bounding_box()['width'])),
            20)
        tab_overflow = page.locator('#workspace-tabs').evaluate(
            '''element => ({
                clientHeight: element.clientHeight,
                scrollHeight: element.scrollHeight,
                overflowY: getComputedStyle(element).overflowY,
            })''')
        self.assertLessEqual(
            tab_overflow['scrollHeight'],
            tab_overflow['clientHeight'] + 1)
        self.assertEqual(tab_overflow['overflowY'], 'hidden')
        expect(toolbar.locator(
                'img[src$="tryton-create.svg"]').last).to_be_visible()
        record_navigation = toolbar.get_by_role(
            'group', name='Record navigation')
        expect(record_navigation).to_be_visible()
        expect(record_navigation).to_contain_text(
            '/%s' % self.active_group_count)
        expect(toolbar.locator('.vs-toolbar-secondary')).to_have_count(1)
        search_toolbar = toolbar.locator('.vs-search-toolbar')
        self.assertGreater(
            search_toolbar.bounding_box()['y'],
            toolbar.locator('.vs-toolbar-group').first.bounding_box()['y'])
        self.assertGreater(
            search_toolbar.bounding_box()['width'],
            toolbar.bounding_box()['width'] * .8)
        search_controls = [
            search_toolbar.locator('.vs-filter-popup > summary'),
            search_toolbar.get_by_placeholder('Search', exact=True),
            search_toolbar.get_by_role('button', name='Search', exact=True),
            search_toolbar.get_by_role(
                'button', name='Bookmark this filter', exact=True),
            search_toolbar.locator('.vs-bookmark-popup > summary'),
            search_toolbar.get_by_role(
                'button', name='Show inactive records'),
            search_toolbar.get_by_role('button', name='Previous page'),
            search_toolbar.get_by_role('button', name='Next page'),
            ]
        search_y = search_controls[0].bounding_box()['y']
        for control in search_controls[1:]:
            self.assertLessEqual(
                abs(control.bounding_box()['y'] - search_y), 2)
        expect(search_toolbar.locator(
            '.vs-page-navigation')).to_be_visible()
        tree = page.locator('.vs-active-panel .vs-table').first
        menu = tree.locator(
            'thead .vs-drag-column summary[aria-label="Columns"]')
        select_all = tree.get_by_role(
            'checkbox', name='Select all records')
        self.assertLess(menu.bounding_box()['x'], select_all.bounding_box()['x'])
        self.assertLessEqual(
            abs(
                menu.bounding_box()['y'] + menu.bounding_box()['height'] / 2
                - select_all.bounding_box()['y']
                - select_all.bounding_box()['height'] / 2),
            2)
        self.assertEqual(round(menu.bounding_box()['width']), 30)
        expect(tree.locator('tbody .vs-drag-column').first).to_be_empty()

        search = toolbar.get_by_placeholder('Search', exact=True)
        old_screen = page.locator('.vs-screen').element_handle()
        executed_searches = []
        page.on('request', lambda request: (
                executed_searches.append(request.url)
                if request.method == 'POST'
                and request.url.endswith('/search')
                else None))
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search/draft'))):
            search.fill('N')
        self.assertTrue(old_screen.evaluate(
            'element => element.isConnected'))
        self.assertEqual(executed_searches, [])
        completion = toolbar.locator('.vs-search-completion')
        expect(completion).to_be_visible()
        name_completion = completion.get_by_role(
            'option', name='Name:', exact=True)
        expect(name_completion).to_be_visible()
        expect(search).to_be_focused()
        name_completion.click()
        expect(search).to_have_value('Name: ')
        expect(search).to_be_focused()
        expect(completion).not_to_be_visible()
        search.press_sequentially('Shell Group Alpha', delay=5)
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        self.assertEqual(executed_searches, [])
        with page.expect_response(lambda response: (
                response.request.method == 'POST'
                and response.url.endswith('/search'))):
            search.press('Enter')
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).not_to_be_visible()
        expect(domain_counts.nth(0)).to_have_text('1')
        expect(domain_counts.nth(1)).to_have_text('1')

        search.fill('N')
        self.assertFalse(completion.evaluate(
            'element => element.hidden'))
        expect(completion.get_by_role(
            'option', name='Name:', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).not_to_be_visible()

        search.fill('')
        toolbar.get_by_role(
            'button', name='Search', exact=True).click()
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        expect(domain_counts.nth(0)).to_have_text(str(self.group_count))
        expect(domain_counts.nth(1)).to_have_text(
            str(self.active_group_count))
        filters = page.locator('details.vs-filter-popup')
        filter_button = filters.locator(
            'summary[aria-label="Filters"]')
        expect(filter_button.locator('svg')).to_be_visible()
        filter_button.click()
        filter_dialog = filters.get_by_role(
            'dialog', name='Filters')
        for title in (
                'ID', 'Created by', 'Created at',
                'Modified by', 'Modified at'):
            expect(filter_dialog.locator(
                    '.vs-filter-field > span',
                    has_text=title)).to_have_count(1)
        self.assertGreater(
            int(filters.evaluate(
                'element => getComputedStyle(element).zIndex')),
            int(page.locator(
                '.vs-table thead .vs-select-column').evaluate(
                    'element => getComputedStyle(element).zIndex')))
        self.assertTrue(page.evaluate("""
            () => {
                const popup = document.querySelector('.vs-filter-menu');
                const header = document.querySelector('.vs-table thead');
                const popupBox = popup.getBoundingClientRect();
                const headerBox = header.getBoundingClientRect();
                const left = Math.max(popupBox.left, headerBox.left);
                const right = Math.min(popupBox.right, headerBox.right);
                const top = Math.max(popupBox.top, headerBox.top);
                const bottom = Math.min(popupBox.bottom, headerBox.bottom);
                if (left >= right || top >= bottom) {
                    return false;
                }
                const element = document.elementFromPoint(
                    left + Math.min(10, (right - left) / 2),
                    top + Math.min(10, (bottom - top) / 2));
                return Boolean(element && element.closest('.vs-filter-menu'));
            }
            """))
        id_range = filters.locator(
            'input[name^="filter__id__"]')
        expect(id_range).to_have_count(2)
        id_field = filter_dialog.locator(
            '.vs-filter-field', has_text='ID').first
        filter_geometry = id_field.evaluate("""
            field => {
                const label = field.querySelector(':scope > span');
                const range = field.querySelector('.vs-filter-range');
                const centers = [
                    label,
                    ...range.children,
                ].map(element => {
                    const box = element.getBoundingClientRect();
                    return box.top + box.height / 2;
                });
                const form = field.closest('.vs-filter-form');
                return {
                    centers,
                    fieldWidth: field.getBoundingClientRect().width,
                    formWidth: form.getBoundingClientRect().width,
                };
            }
            """)
        self.assertLessEqual(
            max(filter_geometry['centers'])
            - min(filter_geometry['centers']),
            2)
        self.assertGreater(
            filter_geometry['fieldWidth'],
            filter_geometry['formWidth'] * .95)
        id_range.nth(0).fill(str(self.alpha_id))
        id_range.nth(1).fill(str(self.alpha_id))
        filters.get_by_role('button', name='Find').click()
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).not_to_be_visible()

        search = toolbar.get_by_placeholder('Search', exact=True)
        search.fill('')
        search.press('Enter')
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        filters = page.locator('details.vs-filter-popup')
        filters.locator('summary[aria-label="Filters"]').click()
        filters.get_by_label('Name', exact=True).fill(
            'Shell Group Beta')
        filters.get_by_role('button', name='Find').click()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).not_to_be_visible()
        page.get_by_role(
            'button', name='Bookmark this filter').click()
        bookmark_dialog = page.locator('#modal')
        bookmark_dialog.get_by_label(
            'Bookmark Name').fill('Only beta')
        bookmark_dialog.get_by_role(
            'button', name='Save', exact=True).click()
        expect(page.get_by_role(
                'button', name='Remove this bookmark')).to_be_visible()

        search = toolbar.get_by_placeholder('Search', exact=True)
        with page.expect_response(
                lambda response: response.url.endswith('/search/draft')):
            search.fill('N')
        expect(page.get_by_role(
            'button', name='Remove this bookmark')).to_have_count(0)
        expect(page.get_by_role(
            'button', name='Bookmark this filter')).to_be_disabled()
        search.fill('')
        search.press('Enter')
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        bookmarks = page.locator('details.vs-bookmark-popup')
        bookmarks.locator(
            'summary[aria-label="Bookmarks"]').click()
        bookmarks.get_by_role(
            'menuitem', name='Only beta', exact=True).click()
        expect(page.get_by_text(
                'Shell Group Beta', exact=True)).to_be_visible()
        expect(page.get_by_text(
                'Shell Group Alpha', exact=True)).not_to_be_visible()
        page.get_by_role(
            'button', name='Remove this bookmark').click()
        page.get_by_label('Bookmarks').click()
        expect(page.get_by_role(
                'menuitem', name='Only beta', exact=True)).to_have_count(0)

        page.locator('[aria-label="Columns"]').click()
        column_popup = page.locator(
            '.vs-column-popup .vs-popup-menu')
        self.assertGreater(
            int(column_popup.evaluate(
                'element => getComputedStyle(element).zIndex')),
            int(page.locator(
                '.vs-table thead th').nth(1).evaluate(
                    'element => getComputedStyle(element).zIndex')))
        self.assertTrue(page.evaluate("""
            () => {
                const popup = document.querySelector(
                    '.vs-column-popup .vs-popup-menu');
                const box = popup.getBoundingClientRect();
                const element = document.elementFromPoint(
                    Math.min(box.right - 1, box.left + 10),
                    Math.min(box.bottom - 1, box.top + 10));
                return Boolean(element && element.closest(
                    '.vs-column-popup .vs-popup-menu'));
            }
        """))
        expect(column_popup.get_by_role(
                'menuitem', name='Copy Selected Records')).to_be_visible()
        expect(column_popup.get_by_role(
                'menuitem', name='Reset Column Widths')).to_be_visible()
        active = page.locator(
            '.vs-column-option',
            has_text='Active').get_by_role('checkbox')
        active.check()
        self.assertTrue(page.locator(
            'details.vs-column-popup').evaluate(
                'element => element.open'))
        expect(page.get_by_role(
                'button', name='Active', exact=True)).to_be_visible()
        with page.expect_response(
                lambda response:
                response.url.endswith('/tree/columns/width')
                and response.request.method == 'POST'):
            page.locator('[data-reset-column-widths]').click()
        self.assertFalse(page.locator(
            'details.vs-column-popup').evaluate(
                'element => element.open'))
        selected_row = page.locator('.vs-table tbody tr').first
        selected_name = selected_row.locator('td').nth(2).inner_text()
        with page.expect_response(
                lambda response:
                '/record/' in response.url
                and response.url.endswith('/select')
                and response.request.method == 'POST'):
            selected_row.get_by_role('checkbox', name='Select record').check()
        page.context.grant_permissions([
            'clipboard-read', 'clipboard-write'])
        page.locator('[aria-label="Columns"]').click()
        page.get_by_role(
            'menuitem', name='Copy Selected Records').click()
        expect(page.locator('details.vs-column-popup')).not_to_have_attribute(
            'open')
        self.assertIn(selected_name, page.evaluate(
            'navigator.clipboard.readText()'))
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_role(
                'button', name='Active', exact=True)).to_be_visible()
        page.get_by_role(
            'button', name='Dynamic Selections', exact=True).click()
        expect(page.get_by_role(
            'button', name='Icon', exact=True)).to_be_visible()
        filters = page.locator('details.vs-filter-popup')
        filters.locator('summary[aria-label="Filters"]').click()
        icon_filter = page.get_by_role(
            'dialog', name='Filters').get_by_role(
                'combobox', name='Icon', exact=True)
        expect(icon_filter).to_be_visible()
        self.assertGreater(icon_filter.locator('option').count(), 1)
        page.reload(wait_until='domcontentloaded')
        expect(page.get_by_role(
                'button', name='Icon', exact=True)).to_be_visible()

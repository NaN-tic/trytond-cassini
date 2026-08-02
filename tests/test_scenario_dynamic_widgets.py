import json
from unittest.mock import patch

from playwright.sync_api import Page, expect
from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.cassini.tests.tools import WebTestCase
from trytond.modules.voyager.tests.tools import browser


class TestDynamicWidgets(WebTestCase):
    modules = ['cassini', 'babi']
    timeout = 20000

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            pool = Pool()
            ActionWindow = pool.get('ir.action.act_window')
            ActionWindowView = pool.get('ir.action.act_window.view')
            BabiTable = pool.get('babi.table')
            BabiWidget = pool.get('babi.widget')
            Dashboard = pool.get('babi.dashboard')
            DashboardItem = pool.get('babi.dashboard.item')
            Menu = pool.get('ir.ui.menu')
            Site = pool.get('www.site')
            View = pool.get('ir.ui.view')
            Widget = pool.get('cassini.test.widget')

            chart = json.dumps({
                    'data': [{
                            'type': 'bar',
                            'name': 'Cassini chart',
                            'x': ['A', 'B'],
                            'y': [2, 4],
                            }],
                    'layout': {'title': 'Cassini chart'},
                    'config': {'displaylogo': False},
                    })
            record, = Widget.create([{
                        'char_value': 'Dynamic widgets',
                        'richtext_value': '{"cassini": true}',
                        'text_value': chart,
                        }])
            view, = View.create([{
                        'model': 'cassini.test.widget',
                        'type': 'form',
                        'data': (
                            '<form col="1">'
                            '<label name="richtext_value"/>'
                            '<field name="richtext_value" widget="code" '
                            'language="json" height="260"/>'
                            '<label name="text_value"/>'
                            '<field name="text_value" widget="chart" '
                            'height="260"/>'
                            '<button name="open_dashboard" '
                            'string="Open Dashboard"/>'
                            '</form>'),
                        }])
            window, = ActionWindow.create([{
                        'name': 'Cassini Dynamic Widgets',
                        'res_model': 'cassini.test.widget',
                        'domain': '[["id", "=", %d]]' % record.id,
                        'context': '{}',
                        'search_value': '[]',
                        }])
            ActionWindowView.create([{
                        'sequence': 1,
                        'view': view.id,
                        'act_window': window.id,
                        }])

            table, = BabiTable.create([{
                        'name': 'Cassini Dashboard Source',
                        'type': 'table',
                        'internal_name': 'cassini_dashboard_source',
                        'query': 'SELECT 1 AS value',
                        'timeout': 30,
                        'preview_limit': 10,
                        }])
            with patch.object(
                    BabiWidget, 'check_parameters', lambda self: None):
                widget, = BabiWidget.create([{
                            'name': 'Cassini Dashboard Chart',
                            'type': 'value',
                            'table': table.id,
                            'timeout': 30,
                            'limit': 1000,
                            'show_title': True,
                            'show_legend': False,
                            'static': False,
                            'show_toolbox': 'on-hover',
                            'image_format': 'svg',
                            }])
            dashboard, = Dashboard.create([{
                        'name': 'Cassini Dashboard',
                        }])
            DashboardItem.create([{
                        'dashboard': dashboard.id,
                        'widget': widget.id,
                        'colspan': 2,
                        'height': 260,
                        }])
            Menu.create([{
                        'name': 'Cassini Dynamic Widgets',
                        'action': str(window),
                        }])
            if not Site.search([('type', '=', 'cassini')]):
                Site.create([{
                            'name': 'Cassini',
                            'type': 'cassini',
                            'url': 'http://localhost/',
                            }])
            cls.widget_id = widget.id
            cls.BabiWidget = BabiWidget
            transaction.commit()

    @browser()
    def test(self, page: Page):
        page.add_init_script('''
            window.CassiniMonaco = {
                KeyMod: {CtrlCmd: 1},
                KeyCode: {KeyS: 2},
                editor: {
                    create(host, options) {
                        let value = options.value || "";
                        const changes = [];
                        host.textContent = value;
                        return {
                            getModel() {
                                return {
                                    onDidChangeContent(callback) {
                                        changes.push(callback);
                                    },
                                };
                            },
                            onDidBlurEditorText() {},
                            addCommand() {},
                            getValue() { return value; },
                            setValue(next) {
                                value = next;
                                host.textContent = value;
                                changes.forEach(callback => callback());
                            },
                            dispose() { host.dataset.disposed = "true"; },
                        };
                    },
                },
            };
            window.Plotly = {
                newPlot(node, data) {
                    node.dataset.plotlyRendered = "true";
                    node.dataset.plotlyType = data[0].type;
                    return Promise.resolve();
                },
                purge() {},
            };
        ''')
        page.goto(
            f'{self.base_url}/{self.database}/cassini/',
            wait_until='domcontentloaded')
        page.locator('#username').fill(self.user)
        page.locator('#password').fill(self.password)
        page.get_by_role('button', name='Sign in').click()
        page.locator('[data-panel-option="menu"]').click()
        page.get_by_role(
            'button', name='Cassini Dynamic Widgets', exact=True).click()

        code = page.locator('[data-code-widget]')
        expect(code).to_be_visible()
        expect(code.locator('[data-code-editor]')).to_contain_text(
            '{"cassini": true}')
        expect(code.locator('[data-code-source]')).to_have_class(
            'vs-input vs-code-source vs-code-source-ready')
        chart = page.locator(
            '[data-field="text_value"] [data-cassini-chart]')
        expect(chart).to_have_attribute('data-plotly-rendered', 'true')
        expect(chart).to_have_attribute('data-plotly-type', 'bar')

        with page.expect_response(
                lambda response: '/field/richtext_value' in response.url):
            code.evaluate('''element => {
                element._cassiniEditor.setValue('{"updated": true}');
            }''')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator(
            '[data-code-source]')).to_have_value('{"updated": true}')

        dashboard_chart = json.dumps({
                'data': [{
                        'type': 'bar',
                        'name': 'Dashboard',
                        'x': ['A'],
                        'y': [5],
                        }],
                'layout': {},
                'config': {},
                })
        with patch.object(
                self.BabiWidget, 'on_change_with_chart',
                lambda self, name=None: dashboard_chart):
            page.get_by_role(
                'button', name='Open Dashboard', exact=True).click()
            dashboard = page.locator('.vs-dashboard-screen')
            expect(dashboard).to_be_visible()
            expect(dashboard.get_by_role(
                'heading', name='Cassini Dashboard')).to_be_visible()
            dashboard_plot = dashboard.locator('[data-cassini-chart]')
            expect(dashboard_plot).to_have_attribute(
                'data-plotly-rendered', 'true')
            dashboard.get_by_role('button', name='Reload/Undo').click()
            expect(dashboard.locator(
                '[data-cassini-chart]')).to_have_attribute(
                    'data-plotly-rendered', 'true')
            page.get_by_role(
                'tab', name='Cassini Dynamic Widgets', exact=True).click()
            page.get_by_role(
                'button', name='Open Dashboard', exact=True).click()
            expect(page.get_by_role(
                'tab', name='Cassini Dashboard', exact=True)).to_have_count(1)

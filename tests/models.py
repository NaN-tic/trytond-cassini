from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.pyson import Bool, Eval


class Monetary(fields.Numeric):
    """Test field with the same client definition as currency.Monetary."""

    def __init__(self, string='', currency=None, **kwargs):
        super().__init__(string, **kwargs)
        self.currency = currency

    def definition(self, model, language):
        definition = super().definition(model, language)
        definition['symbol'] = self.currency
        definition['monetary'] = True
        return definition


class WidgetCurrency(ModelSQL, ModelView):
    'Cassini Test Widget Currency'
    __name__ = 'cassini.test.widget.currency'

    name = fields.Char('Name', required=True)
    symbol = fields.Char('Symbol', required=True)

    def get_symbol(self, sign):
        return self.symbol, 1


class Widget(ModelSQL, ModelView):
    'Cassini Test Widget'
    __name__ = 'cassini.test.widget'
    _rec_name = 'char_value'
    _history = True

    binary_value = fields.Binary('Binary')
    binary_filename = fields.Char('Binary Filename')
    boolean_value = fields.Boolean('Boolean')
    callto_value = fields.Char('Call')
    char_value = fields.Char('Character', required=True)
    color_value = fields.Char('Color')
    currency_value = fields.Many2One(
        'cassini.test.widget.currency', 'Currency')
    date_value = fields.Date('Date')
    datetime_value = fields.DateTime('Date Time')
    dict_value = fields.Dict(None, 'Dictionary')
    document_value = fields.Binary('Document')
    document_filename = fields.Char('Document Filename')
    email_value = fields.Char('Email')
    float_value = fields.Float('Float')
    html_value = fields.Text('HTML')
    image_value = fields.Binary('Image')
    integer_value = fields.Integer('Integer')
    many2many_value = fields.Many2Many(
        'cassini.test.widget-res.group', 'widget', 'group',
        'Many to Many')
    many2one_value = fields.Many2One('res.group', 'Many to One')
    multiselection_value = fields.MultiSelection([
            ('first', 'First'),
            ('second', 'Second'),
            ], 'Multi-selection')
    monetary_value = Monetary('Monetary', currency='currency_value')
    numeric_value = fields.Numeric('Numeric')
    one2many_value = fields.One2Many(
        'cassini.test.widget.child', 'widget', 'One to Many',
        add_remove=[])
    one2one_value = fields.One2One(
        'cassini.test.widget-res.group.one2one',
        'widget', 'group', 'One to One')
    password_value = fields.Char('Password')
    progress_value = fields.Float('Progress')
    pyson_value = fields.Text('PYSON')
    reference_value = fields.Reference(
        'Reference', selection=[
                (None, ''),
                ('res.group', 'Group'),
                ])
    richtext_value = fields.Text('Rich Text')
    selection_value = fields.Selection([
            ('draft', 'Draft'),
            ('marked', 'Marked'),
            ], 'Selection')
    sip_value = fields.Char('SIP')
    text_value = fields.Text('Text')
    time_value = fields.Time('Time')
    timedelta_value = fields.TimeDelta('Time Delta')
    timestamp_value = fields.Timestamp('Timestamp')
    url_value = fields.Char('URL')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'mark': {'icon': 'tryton-ok'},
                'change_character': {},
                'open_dashboard': {},
                })

    @staticmethod
    def default_selection_value():
        return 'draft'

    @classmethod
    @ModelView.button
    def mark(cls, records):
        cls.write(records, {'selection_value': 'marked'})

    @ModelView.button_change('char_value')
    def change_character(self):
        self.char_value = 'Instance ' + self.char_value

    def on_scan_code(self, code):
        self.char_value = code

    @classmethod
    @ModelView.button
    def open_dashboard(cls, records):
        pool = Pool()
        Dashboard = pool.get('babi.dashboard')
        dashboards = Dashboard.search([
                ('name', '=', 'Cassini Dashboard'),
                ], limit=1)
        if not dashboards:
            return
        dashboard, = dashboards
        return {
            'name': dashboard.name,
            'type': 'babi.action.dashboard',
            'dashboard': dashboard.id,
            }


class PysonState(ModelSQL, ModelView):
    'Cassini Test PYSON State'
    __name__ = 'cassini.test.pyson_state'

    street_value = fields.Function(
        fields.Text('Street'), 'on_change_with_street_value',
        setter='set_street_value')
    street_unstructured = fields.Text('Street Unstructured')
    street_name_value = fields.Char(
        'Street Name',
        states={
            'invisible': (
                Eval('street_unstructured') & ~Eval('street_name_value')),
            })
    street_number_value = fields.Char(
        'Street Number',
        states={'readonly': Bool(Eval('street_unstructured'))})
    street_area_value = fields.Char(
        'Street Area',
        states={'required': Bool(Eval('street_unstructured'))})

    @fields.depends('street_value', 'street_unstructured')
    def on_change_street_value(self):
        self.street_unstructured = self.street_value

    @fields.depends('street_unstructured')
    def on_change_with_street_value(self, name=None):
        return self.street_unstructured

    @classmethod
    def set_street_value(cls, records, name, value):
        cls.write(records, {'street_unstructured': value})


class WidgetGroup(ModelSQL):
    'Cassini Test Widget - Group'
    __name__ = 'cassini.test.widget-res.group'

    widget = fields.Many2One(
        'cassini.test.widget', 'Widget',
        required=True, ondelete='CASCADE')
    group = fields.Many2One(
        'res.group', 'Group', required=True, ondelete='CASCADE')


class WidgetGroupOne2One(ModelSQL):
    'Cassini Test Widget - Group One to One'
    __name__ = 'cassini.test.widget-res.group.one2one'

    widget = fields.Many2One(
        'cassini.test.widget', 'Widget',
        required=True, ondelete='CASCADE')
    group = fields.Many2One(
        'res.group', 'Group', required=True, ondelete='CASCADE')


class WidgetChild(ModelSQL, ModelView):
    'Cassini Test Widget Child'
    __name__ = 'cassini.test.widget.child'

    name = fields.Char('Name', required=True)
    widget = fields.Many2One(
        'cassini.test.widget', 'Widget',
        required=True, ondelete='CASCADE')


class TreeNode(ModelSQL, ModelView):
    'Cassini Test Tree Node'
    __name__ = 'cassini.test.tree.node'

    name = fields.Char('Name', required=True)
    sequence = fields.Integer('Sequence')
    amount = fields.Numeric('Amount')
    parent = fields.Many2One(
        'cassini.test.tree.node', 'Parent',
        ondelete='CASCADE')
    children = fields.One2Many(
        'cassini.test.tree.node', 'parent', 'Children')

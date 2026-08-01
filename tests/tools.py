from trytond.pool import Pool
from trytond.transaction import Transaction

from trytond.modules.voyager.tests.tools import WebTestCase as VoyagerWebTestCase


class WebTestCase(VoyagerWebTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with Transaction().start(cls.database, 1) as transaction:
            ConfigItem = Pool().get('ir.module.config_wizard.item')
            open_items = ConfigItem.search([('state', '=', 'open')])
            if open_items:
                ConfigItem.write(open_items, {'state': 'done'})
            transaction.commit()

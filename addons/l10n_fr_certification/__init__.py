# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import models
from openerp import api, SUPERUSER_ID

def _setup_inalterability(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # enable ping for this module
    env['publisher_warranty.contract'].update_notification(cron_mode=True)

    fr_companies = env['res.company'].search([('partner_id.country_id.code', '=', 'FR')])
    if fr_companies:
        # create the securisation sequence per company
        fr_companies._create_secure_sequence()

        #reset the update_posted field on journals
        journals = env['account.journal'].search([('company_id', 'in', fr_companies.ids),
                                                  ('type', 'like', 'sale')])
        for journal in journals:
            journal.write({'update_posted': False, 'l10n_fr_b2c': True})

# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re
from werkzeug import urls

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import email_split, float_is_zero, pycompat

from odoo.addons import decimal_precision as dp


class HrExpense(models.Model):

    _name = "hr.expense"
    _inherit = ['mail.thread']
    _description = "Expense"
    _order = "date desc, id desc"

    name = fields.Char(string='Expense Description', readonly=True, required=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]})
    date = fields.Date(readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, default=fields.Date.context_today, string="Expense Date")
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1))
    product_id = fields.Many2one('product.product', string='Product', readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, domain=[('can_be_expensed', '=', True)], required=True)
    product_uom_id = fields.Many2one('product.uom', string='Unit of Measure', required=True, readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, default=lambda self: self.env['product.uom'].search([], limit=1, order='id'))
    unit_amount = fields.Float(string='Unit Price', readonly=True, required=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, digits=dp.get_precision('Product Price'))
    quantity = fields.Float(required=True, readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, digits=dp.get_precision('Product Unit of Measure'), default=1)
    tax_ids = fields.Many2many('account.tax', 'expense_tax', 'expense_id', 'tax_id', string='Taxes', states={'done': [('readonly', True)], 'post': [('readonly', True)]})
    untaxed_amount = fields.Float(string='Subtotal', store=True, compute='_compute_amount', digits=dp.get_precision('Account'))
    total_amount = fields.Float(string='Total', store=True, compute='_compute_amount', digits=dp.get_precision('Account'))
    company_id = fields.Many2one('res.company', string='Company', readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, default=lambda self: self.env.user.company_id)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]}, default=lambda self: self.env.user.company_id.currency_id)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', states={'post': [('readonly', True)], 'done': [('readonly', True)]}, oldname='analytic_account')
    account_id = fields.Many2one('account.account', string='Account', states={'post': [('readonly', True)], 'done': [('readonly', True)]}, default=lambda self: self.env['ir.property'].get('property_account_expense_categ_id', 'product.category'))
    description = fields.Text()
    payment_mode = fields.Selection([("own_account", "Employee (to reimburse)"), ("company_account", "Company")], default='own_account', states={'done': [('readonly', True)], 'post': [('readonly', True)]}, string="Payment By")
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    state = fields.Selection([
        ('draft', 'To Submit'),
        ('reported', 'Reported'),
        ('done', 'Posted'),
        ('refused', 'Refused')
        ], compute='_compute_state', string='Status', copy=False, index=True, readonly=True, store=True,
        help="Status of the expense.")
    sheet_id = fields.Many2one('hr.expense.sheet', string="Expense Report", readonly=True, copy=False)
    reference = fields.Char(string="Bill Reference")

    @api.depends('sheet_id', 'sheet_id.account_move_id', 'sheet_id.state')
    def _compute_state(self):
        for expense in self:
            if not expense.sheet_id:
                expense.state = "draft"
            elif expense.sheet_id.state == "cancel":
                expense.state = "refused"
            elif not expense.sheet_id.account_move_id:
                expense.state = "reported"
            else:
                expense.state = "done"

    @api.depends('quantity', 'unit_amount', 'tax_ids', 'currency_id')
    def _compute_amount(self):
        for expense in self:
            expense.untaxed_amount = expense.unit_amount * expense.quantity
            taxes = expense.tax_ids.compute_all(expense.unit_amount, expense.currency_id, expense.quantity, expense.product_id, expense.employee_id.user_id.partner_id)
            expense.total_amount = taxes.get('total_included')

    @api.multi
    def _compute_attachment_number(self):
        attachment_data = self.env['ir.attachment'].read_group([('res_model', '=', 'hr.expense'), ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        attachment = dict((data['res_id'], data['res_id_count']) for data in attachment_data)
        for expense in self:
            expense.attachment_number = attachment.get(expense.id, 0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            if not self.name:
                self.name = self.product_id.display_name or ''
            self.unit_amount = self.product_id.price_compute('standard_price')[self.product_id.id]
            self.product_uom_id = self.product_id.uom_id
            self.tax_ids = self.product_id.supplier_taxes_id
            account = self.product_id.product_tmpl_id._get_product_accounts()['expense']
            if account:
                self.account_id = account

    @api.onchange('product_uom_id')
    def _onchange_product_uom_id(self):
        if self.product_id and self.product_uom_id.category_id != self.product_id.uom_id.category_id:
            raise UserError(_('Selected Unit of Measure does not belong to the same category as the product Unit of Measure'))

    @api.multi
    def view_sheet(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'hr.expense.sheet',
            'target': 'current',
            'res_id': self.sheet_id.id
        }

    @api.multi
    def submit_expenses(self):
        if any(expense.state != 'draft' for expense in self):
            raise UserError(_("You cannot report twice the same line!"))
        if len(self.mapped('employee_id')) != 1:
            raise UserError(_("You cannot report expenses for different employees in the same report!"))
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'hr.expense.sheet',
            'target': 'current',
            'context': {
                'default_expense_line_ids': [line.id for line in self],
                'default_employee_id': self[0].employee_id.id,
                'default_name': self[0].name if len(self.ids) == 1 else ''
            }
        }

    def _prepare_move_line(self, line):
        '''
        This function prepares move line of account.move related to an expense
        '''
        partner_id = self.employee_id.address_home_id.commercial_partner_id.id
        return {
            'date_maturity': line.get('date_maturity'),
            'partner_id': partner_id,
            'name': line['name'][:64],
            'debit': line['price'] > 0 and line['price'],
            'credit': line['price'] < 0 and - line['price'],
            'account_id': line['account_id'],
            'analytic_line_ids': line.get('analytic_line_ids'),
            'amount_currency': line['price'] > 0 and abs(line.get('amount_currency')) or - abs(line.get('amount_currency')),
            'currency_id': line.get('currency_id'),
            'tax_line_id': line.get('tax_line_id'),
            'tax_ids': line.get('tax_ids'),
            'quantity': line.get('quantity', 1.00),
            'product_id': line.get('product_id'),
            'product_uom_id': line.get('uom_id'),
            'analytic_account_id': line.get('analytic_account_id'),
            'payment_id': line.get('payment_id'),
        }

    @api.multi
    def _compute_expense_totals(self, company_currency, account_move_lines, move_date):
        '''
        internal method used for computation of total amount of an expense in the company currency and
        in the expense currency, given the account_move_lines that will be created. It also do some small
        transformations at these account_move_lines (for multi-currency purposes)

        :param account_move_lines: list of dict
        :rtype: tuple of 3 elements (a, b ,c)
            a: total in company currency
            b: total in hr.expense currency
            c: account_move_lines potentially modified
        '''
        self.ensure_one()
        total = 0.0
        total_currency = 0.0
        for line in account_move_lines:
            line['currency_id'] = False
            line['amount_currency'] = False
            if self.currency_id != company_currency:
                line['currency_id'] = self.currency_id.id
                line['amount_currency'] = line['price']
                line['price'] = self.currency_id.with_context(date=move_date or fields.Date.context_today(self)).compute(line['price'], company_currency)
            total -= line['price']
            total_currency -= line['amount_currency'] or line['price']
        return total, total_currency, account_move_lines

    @api.multi
    def action_move_create(self):
        '''
        main function that is called when trying to create the accounting entries related to an expense
        '''
        move_group_by_sheet = {}
        for expense in self:
            journal = expense.sheet_id.bank_journal_id if expense.payment_mode == 'company_account' else expense.sheet_id.journal_id
            #create the move that will contain the accounting entries
            acc_date = expense.sheet_id.accounting_date or expense.date
            if not expense.sheet_id.id in move_group_by_sheet:
                move = self.env['account.move'].create({
                    'journal_id': journal.id,
                    'company_id': self.env.user.company_id.id,
                    'date': acc_date,
                    'ref': expense.sheet_id.name,
                    # force the name to the default value, to avoid an eventual 'default_name' in the context
                    # to set it to '' which cause no number to be given to the account.move when posted.
                    'name': '/',
                })
                move_group_by_sheet[expense.sheet_id.id] = move
            else:
                move = move_group_by_sheet[expense.sheet_id.id]
            company_currency = expense.company_id.currency_id
            diff_currency_p = expense.currency_id != company_currency
            #one account.move.line per expense (+taxes..)
            move_lines = expense._move_line_get()

            #create one more move line, a counterline for the total on payable account
            payment_id = False
            total, total_currency, move_lines = expense._compute_expense_totals(company_currency, move_lines, acc_date)
            if expense.payment_mode == 'company_account':
                if not expense.sheet_id.bank_journal_id.default_credit_account_id:
                    raise UserError(_("No credit account found for the %s journal, please configure one.") % (expense.sheet_id.bank_journal_id.name))
                emp_account = expense.sheet_id.bank_journal_id.default_credit_account_id.id
                journal = expense.sheet_id.bank_journal_id
                #create payment
                payment_methods = (total < 0) and journal.outbound_payment_method_ids or journal.inbound_payment_method_ids
                journal_currency = journal.currency_id or journal.company_id.currency_id
                payment = self.env['account.payment'].create({
                    'payment_method_id': payment_methods and payment_methods[0].id or False,
                    'payment_type': total < 0 and 'outbound' or 'inbound',
                    'partner_id': expense.employee_id.address_home_id.commercial_partner_id.id,
                    'partner_type': 'supplier',
                    'journal_id': journal.id,
                    'payment_date': expense.date,
                    'state': 'reconciled',
                    'currency_id': diff_currency_p and expense.currency_id.id or journal_currency.id,
                    'amount': diff_currency_p and abs(total_currency) or abs(total),
                    'name': expense.name,
                })
                payment_id = payment.id
            else:
                if not expense.employee_id.address_home_id:
                    raise UserError(_("No Home Address found for the employee %s, please configure one.") % (expense.employee_id.name))
                emp_account = expense.employee_id.address_home_id.property_account_payable_id.id

            aml_name = expense.employee_id.name + ': ' + expense.name.split('\n')[0][:64]
            move_lines.append({
                    'type': 'dest',
                    'name': aml_name,
                    'price': total,
                    'account_id': emp_account,
                    'date_maturity': acc_date,
                    'amount_currency': diff_currency_p and total_currency or False,
                    'currency_id': diff_currency_p and expense.currency_id.id or False,
                    'payment_id': payment_id,
                    })

            #convert eml into an osv-valid format
            lines = [(0, 0, expense._prepare_move_line(x)) for x in move_lines]
            move.with_context(dont_create_taxes=True).write({'line_ids': lines})
            expense.sheet_id.write({'account_move_id': move.id})
            if expense.payment_mode == 'company_account':
                expense.sheet_id.paid_expense_sheets()
        for move in pycompat.values(move_group_by_sheet):
            move.post()
        return True

    @api.multi
    def _prepare_move_line_value(self):
        self.ensure_one()
        if self.account_id:
            account = self.account_id
        elif self.product_id:
            account = self.product_id.product_tmpl_id._get_product_accounts()['expense']
            if not account:
                raise UserError(
                    _("No Expense account found for the product %s (or for its category), please configure one.") % (self.product_id.name))
        else:
            account = self.env['ir.property'].with_context(force_company=self.company_id.id).get('property_account_expense_categ_id', 'product.category')
            if not account:
                raise UserError(
                    _('Please configure Default Expense account for Product expense: `property_account_expense_categ_id`.'))
        aml_name = self.employee_id.name + ': ' + self.name.split('\n')[0][:64]
        move_line = {
            'type': 'src',
            'name': aml_name,
            'price_unit': self.unit_amount,
            'quantity': self.quantity,
            'price': self.total_amount,
            'account_id': account.id,
            'product_id': self.product_id.id,
            'uom_id': self.product_uom_id.id,
            'analytic_account_id': self.analytic_account_id.id,
        }
        return move_line

    @api.multi
    def _move_line_get(self):
        account_move = []
        for expense in self:
            move_line = expense._prepare_move_line_value()
            account_move.append(move_line)

            # Calculate tax lines and adjust base line
            taxes = expense.tax_ids.compute_all(expense.unit_amount, expense.currency_id, expense.quantity, expense.product_id)
            account_move[-1]['price'] = taxes['total_excluded']
            account_move[-1]['tax_ids'] = [(6, 0, expense.tax_ids.ids)]
            for tax in taxes['taxes']:
                account_move.append({
                    'type': 'tax',
                    'name': tax['name'],
                    'price_unit': tax['amount'],
                    'quantity': 1,
                    'price': tax['amount'],
                    'account_id': tax['account_id'] or move_line['account_id'],
                    'tax_line_id': tax['id'],
                })
        return account_move

    @api.multi
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window'].for_xml_id('base', 'action_attachment')
        res['domain'] = [('res_model', '=', 'hr.expense'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'hr.expense', 'default_res_id': self.id}
        return res

    @api.model
    def get_empty_list_help(self, help_message):
        if help_message:
            use_mailgateway = self.env['ir.config_parameter'].sudo().get_param('hr_expense.use_mailgateway')
            alias_record = use_mailgateway and self.env.ref('hr_expense.mail_alias_expense') or False
            if alias_record and alias_record.alias_domain and alias_record.alias_name:
                link = "<a id='o_mail_test' href='mailto:%(email)s?subject=Lunch%%20with%%20customer%%3A%%20%%2412.32'>%(email)s</a>" % {
                    'email': '%s@%s' % (alias_record.alias_name, alias_record.alias_domain)
                }
                return '<p class="oe_view_nocontent_create">%s<br/>%s</p>%s' % (
                    _('Click to add a new expense,'),
                    _('or send receipts by email to %s.') % (link,),
                    help_message)
        return super(HrExpense, self).get_empty_list_help(help_message)

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        if custom_values is None:
            custom_values = {}

        email_address = email_split(msg_dict.get('email_from', False))[0]

        employee = self.env['hr.employee'].search([
            '|',
            ('work_email', 'ilike', email_address),
            ('user_id.email', 'ilike', email_address)
        ], limit=1)

        expense_description = msg_dict.get('subject', '')

        # Match the first occurence of '[]' in the string and extract the content inside it
        # Example: '[foo] bar (baz)' becomes 'foo'. This is potentially the product code
        # of the product to encode on the expense. If not, take the default product instead
        # which is 'Fixed Cost'
        default_product = self.env.ref('hr_expense.product_product_fixed_cost')
        pattern = re.sub(r'[^a-zA-Z]+', ' ', expense_description)
        product = default_product
        exp_products = self.env['product.product'].search([('product_tmpl_id.can_be_expensed', '=', True)])
        for each_exp_prod in exp_products:
            if each_exp_prod.name in pattern:
                product = each_exp_prod
                break
            elif each_exp_prod.code and each_exp_prod.code in pattern:
                product = each_exp_prod
                break

        pattern = '[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?'
        # Match the last occurence of a float in the string
        # Example: '[foo] 50.3 bar 34.5' becomes '34.5'. This is potentially the price
        # to encode on the expense. If not, take 1.0 instead
        expense_price = re.findall(pattern, expense_description)
        # TODO: International formatting
        if not expense_price:
            price = 1.0
        else:
            price = expense_price[-1][0]
            expense_description = expense_description.replace(price, '')
            if employee and employee.company_id.currency_id.symbol in expense_description:
                expense_description = expense_description.replace(employee.company_id.currency_id.symbol, '')
            expense_description = re.sub('[^A-Za-z0-9.]+', ' ', expense_description)
            try:
                price = float(price)
            except ValueError:
                price = 1.0

        custom_values.update({
            'name': expense_description.strip(),
            'employee_id': employee.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'quantity': 1,
            'unit_amount': price,
            'company_id': employee.company_id.id,
        })
        if custom_values.get('employee_id'):
            res = super(HrExpense, self).message_new(msg_dict, custom_values)
            template_id = self.env.ref('hr_expense.email_template_hr_expense_success')
            template_id.send_mail(res.id)
            return res
        else:
            base_partner = self.env.ref('base.partner_root')
            template_id = self.env.ref('hr_expense.email_template_hr_expense_falied')
            template_id.write({'email_to': email_split(msg_dict.get('email_from', False))[0]})
            template_id.sudo().send_mail(base_partner.id, force_send=True)
            return False
        return super(HrExpense, self).message_new(msg_dict, custom_values)

    @api.multi
    def get_access_action(self, access_uid=None):
        """ Instead of the classic form view, redirect to the online invoice for portal users. """
        self.ensure_one()
        user, record = self.env.user, self
        if access_uid:
            user = self.env['res.users'].sudo().browse(access_uid)
            record = self.sudo(user)

        if user.share or self.env.context.get('force_website'):
            try:
                record.check_access_rule('read')
            except exceptions.AccessError:
                pass
            else:
                return {
                    'type': 'ir.actions.act_url',
                    'url': '/my/expenses?',
                    'target': 'self',
                    'res_id': self.id,
                }
        return super(HrExpense, self).get_access_action(access_uid)

    def get_mail_url(self):
        self.ensure_one()
        params = {
            'model': self._name,
            'res_id': self.id,
        }
        params.update(self.employee_id.user_id.partner_id.signup_get_auth_param()[self.employee_id.user_id.partner_id.id])
        res = ('/web?#id=%s&view_type=form&model=%s' %(self.id, params['model']))
        return res

class HrExpenseSheet(models.Model):

    _name = "hr.expense.sheet"
    _inherit = ['mail.thread']
    _description = "Expense Report"
    _order = "accounting_date desc, id desc"

    name = fields.Char(string='Expense Report Summary', required=True)
    expense_line_ids = fields.One2many('hr.expense', 'sheet_id', string='Expense Lines', states={'done': [('readonly', True)], 'post': [('readonly', True)]}, copy=False)
    state = fields.Selection([('submit', 'Submitted'),
                              ('approve', 'Approved'),
                              ('post', 'Posted'),
                              ('done', 'Paid'),
                              ('cancel', 'Refused')
                              ], string='Status', index=True, readonly=True, track_visibility='onchange', copy=False, default='submit', required=True,
        help='Expense Report State')
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, readonly=True, states={'submit': [('readonly', False)]}, default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1))
    address_id = fields.Many2one('res.partner', string="Employee Home Address")
    payment_mode = fields.Selection([("own_account", "Employee (to reimburse)"), ("company_account", "Company")], related='expense_line_ids.payment_mode', default='own_account', readonly=True, string="Payment By")
    responsible_id = fields.Many2one('res.users', 'Validation By', readonly=True, copy=False, states={'submit': [('readonly', False)], 'submit': [('readonly', False)]})
    total_amount = fields.Float(string='Total Amount', store=True, compute='_compute_amount', digits=dp.get_precision('Account'))
    company_id = fields.Many2one('res.company', string='Company', readonly=True, states={'submit': [('readonly', False)]}, default=lambda self: self.env.user.company_id)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True, states={'submit': [('readonly', False)]}, default=lambda self: self.env.user.company_id.currency_id)
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    journal_id = fields.Many2one('account.journal', string='Expense Journal', states={'done': [('readonly', True)], 'post': [('readonly', True)]},
        default=lambda self: self.env['ir.model.data'].xmlid_to_object('hr_expense.hr_expense_account_journal') or self.env['account.journal'].search([('type', '=', 'purchase')], limit=1),
        help="The journal used when the expense is done.")
    bank_journal_id = fields.Many2one('account.journal', string='Bank Journal', states={'done': [('readonly', True)], 'post': [('readonly', True)]}, default=lambda self: self.env['account.journal'].search([('type', 'in', ['case', 'bank'])], limit=1), help="The payment method used when the expense is paid by the company.")
    accounting_date = fields.Date(string="Accounting Date")
    account_move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='restrict', copy=False)
    department_id = fields.Many2one('hr.department', string='Department', states={'post': [('readonly', True)], 'done': [('readonly', True)]})

    @api.multi
    def check_consistency(self):
        if any(sheet.employee_id != self[0].employee_id for sheet in self):
            raise UserError(_("Expenses must belong to the same Employee."))

        expense_lines = self.mapped('expense_line_ids')
        if expense_lines and any(expense.payment_mode != expense_lines[0].payment_mode for expense in expense_lines):
            raise UserError(_("Expenses must have been paid by the same entity (Company or employee)"))

    @api.model
    def create(self, vals):
        sheet = super(HrExpenseSheet, self).create(vals)
        self.check_consistency()
        if vals.get('employee_id'):
            sheet._add_followers()
        return sheet

    @api.multi
    def write(self, vals):
        res = super(HrExpenseSheet, self).write(vals)
        self.check_consistency()
        if vals.get('employee_id'):
            self._add_followers()
        return res

    @api.multi
    def unlink(self):
        for expense in self:
            if expense.state == "post":
                raise UserError(_("You cannot delete a posted expense."))
        super(HrExpenseSheet, self).unlink()

    @api.multi
    def set_to_paid(self):
        self.write({'state': 'done'})

    @api.multi
    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'approve':
            return 'hr_expense.mt_expense_approved'
        elif 'state' in init_values and self.state == 'submit':
            return 'hr_expense.mt_expense_confirmed'
        elif 'state' in init_values and self.state == 'cancel':
            return 'hr_expense.mt_expense_refused'
        elif 'state' in init_values and self.state == 'done':
            return 'hr_expense.mt_expense_paid'
        return super(HrExpenseSheet, self)._track_subtype(init_values)

    def _add_followers(self):
        user_ids = []
        employee = self.employee_id
        if employee.user_id:
            user_ids.append(employee.user_id.id)
        if employee.parent_id:
            user_ids.append(employee.parent_id.user_id.id)
        if employee.department_id and employee.department_id.manager_id and employee.parent_id != employee.department_id.manager_id:
            user_ids.append(employee.department_id.manager_id.user_id.id)
        self.message_subscribe_users(user_ids=user_ids)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        self.address_id = self.employee_id.address_home_id
        self.department_id = self.employee_id.department_id

    @api.one
    @api.depends('expense_line_ids', 'expense_line_ids.total_amount', 'expense_line_ids.currency_id')
    def _compute_amount(self):
        if len(self.expense_line_ids.mapped('currency_id')) < 2:
            self.total_amount = sum(self.expense_line_ids.mapped('total_amount'))
        else:
            self.total_amount = 0.0

    # FIXME: A 4 command is missing to explicitly declare the one2many relation
    # between the sheet and the lines when using 'default_expense_line_ids':[ids]
    # in the context. A fix from chm-odoo should come since
    # several saas versions but sadly I had to add this hack to avoid this
    # issue
    @api.model
    def _add_missing_default_values(self, values):
        values = super(HrExpenseSheet, self)._add_missing_default_values(values)
        if self.env.context.get('default_expense_line_ids', False):
            lines_to_add = []
            for line in values.get('expense_line_ids', []):
                if line[0] == 1:
                    lines_to_add.append([4, line[1], False])
            values['expense_line_ids'] = lines_to_add + values['expense_line_ids']
        return values

    @api.one
    def _compute_attachment_number(self):
        self.attachment_number = sum(self.expense_line_ids.mapped('attachment_number'))

    @api.multi
    def refuse_expenses(self, reason):
        self.write({'state': 'cancel'})
        for sheet in self:
            body = (_("Your Expense %s has been refused.<br/><ul class=o_timeline_tracking_value_list><li>Reason<span> : </span><span class=o_timeline_tracking_value>%s</span></li></ul>") % (sheet.name, reason))
            sheet.message_post(body=body)

    @api.multi
    def approve_expense_sheets(self):
        self.write({'state': 'approve', 'responsible_id': self.env.user.id})

    @api.multi
    def paid_expense_sheets(self):
        self.write({'state': 'done'})

    @api.multi
    def reset_expense_sheets(self):
        return self.write({'state': 'submit'})

    @api.multi
    def action_sheet_move_create(self):
        if any(sheet.state != 'approve' for sheet in self):
            raise UserError(_("You can only generate accounting entry for approved expense(s)."))

        if any(not sheet.journal_id for sheet in self):
            raise UserError(_("Expenses must have an expense journal specified to generate accounting entries."))

        expense_line_ids = self.mapped('expense_line_ids')\
            .filtered(lambda r: not float_is_zero(r.total_amount, precision_rounding=(r.currency_id or self.env.user.company_id.currency_id).rounding))
        res = expense_line_ids.action_move_create()

        if not self.accounting_date:
            self.accounting_date = self.account_move_id.date

        if self.payment_mode == 'own_account' and expense_line_ids:
            self.write({'state': 'post'})
        else:
            self.write({'state': 'done'})
        return res

    @api.multi
    def action_get_attachment_view(self):
        res = self.env['ir.actions.act_window'].for_xml_id('base', 'action_attachment')
        res['domain'] = [('res_model', '=', 'hr.expense'), ('res_id', 'in', self.expense_line_ids.ids)]
        res['context'] = {'default_res_model': 'hr.expense.sheet', 'default_res_id': self.id}
        return res

    @api.one
    @api.constrains('expense_line_ids')
    def _check_employee(self):
        employee_ids = self.expense_line_ids.mapped('employee_id')
        if len(employee_ids) > 1 or (len(employee_ids) == 1 and employee_ids != self.employee_id):
            raise ValidationError(_('You cannot add expense lines of another employee.'))

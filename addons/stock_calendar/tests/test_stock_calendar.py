# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import common


class TestsStockCalendar(common.TransactionCase):

    def setUp(self):
        super(TestsStockCalendar, self).setUp()

        # Create a partner
        self.stock_warehouse0_id = self.ref('stock.warehouse0')
        self.purchase_route_warehouse0_buy_id = self.ref('purchase.route_warehouse0_buy')
        self.stock_picking_type_out_id = self.ref('stock.picking_type_out')
        self.stock_location_id = self.ref('stock.stock_location_stock')
        self.stock_location_customer_id = self.ref('stock.stock_location_customers')

        self.res_partner_id = self.env['res.partner'].create({
            'name': 'Supplier',
            'supplier': 1
        })

        # Create a calendar
        self.resource_calendar_id = self.env['work.calendar'].create({
            'name': 'Calendar',
            'attendance_ids': [(0, 0, {
                'name': 'Thursday',
                'dayofweek': '3',
                'hour_from': 8,
                'hour_to': 9
            })]
        })

        # Create a product A with orderpoint with a calendar
        self.calendar_product_id = self.env['product.product'].create({
            'name': 'Calendar Product',
            'seller_ids': [(0, 0, {
                'name': self.res_partner_id.id,
                'delay': 1
            })],
            'orderpoint_ids': [(0, 0, {
                'name': 'Product A Truck',
                'calendar_id': self.resource_calendar_id.id,
                'product_min_qty': 0,
                'product_max_qty': 10,
                'warehouse_id': self.stock_warehouse0_id
            })]
        })

        # Create delivery order with product A
        self.pick_out_calendar = self._create_stock_picking('Delivery order for procurement', self.calendar_product_id.name, 3.00)

        # Create other delivery order with product A that we will give a later date afterwards (date between the two)
        self.pick_out_calendar2 = self._create_stock_picking('Delivery order for procurement2', 'stock_move_2', 4.00)

        # Create other delivery order with product A that we will give an even later date, so it should not be taken into account
        self.pick_out_calendar3 = self._create_stock_picking('Delivery order for procurement3', 'stock_move_3', 11.00)

    def _create_stock_picking(self, pickname, movelinename, productqty):
        return self.env['stock.picking'].create({
            'name': pickname,
            'partner_id': self.res_partner_id.id,
            'picking_type_id': self.stock_picking_type_out_id,
            'location_id': self.stock_location_id,
            'location_dest_id': self.stock_location_customer_id,
            'move_lines': [(0, 0, {'name': movelinename,
                                   'product_id': self.calendar_product_id.id,
                                   'product_uom': self.calendar_product_id.uom_id.id,
                                   'product_uom_qty': productqty,
                                   'location_id': self.stock_location_id,
                                   'location_dest_id': self.stock_location_customer_id,
                                   'procure_method': 'make_to_stock'})]
        })

    def test_stock_calendar(self):
        # Put different dates in pickings, confirm them, run schedulers and check that the procurement generated by the
        # orderpoint is taking the calendar into account.  Make sure also that the purchase order creates a datetime.
        self.calendar_product_id.write({'route_ids': [(4, self.purchase_route_warehouse0_buy_id)]})
        today8 = datetime.now() + timedelta(days=7)
        today21 = datetime.now() + timedelta(days=21)
        self.pick_out_calendar2.move_lines.write({'date': fields.Datetime.to_string(today8), 'date_expected': fields.Datetime.to_string(today8)})
        self.pick_out_calendar3.move_lines.write({'date_expected': fields.Datetime.to_string(today21), 'date': fields.Datetime.to_string(today21)})

        # We need to confirm pickings and run the schedulers
        self.pick_out_calendar.action_confirm()
        self.pick_out_calendar2.action_confirm()
        self.pick_out_calendar3.action_confirm()

        # Check .procurements generated
        Procurementorder = self.env['procurement.order']
        Procurementorder.run_scheduler()
        procurement = Procurementorder.search([('product_id', '=', self.calendar_product_id.id)], limit=1)
        self.assertEqual(len(procurement), 1, 'should have one procurement')
        self.assertEqual(procurement.product_qty, 17, 'It should have taken the two first pickings into account for the virtual stock for the orderpoint, not the third')
        self.assertEqual(fields.Datetime.from_string(procurement.next_delivery_date).weekday(), 3, 'The next delivery date should be on a Thursday')
        purchase_line_id_date_planned = fields.Datetime.from_string(procurement.purchase_line_id.date_planned).weekday()
        self.assertEqual(purchase_line_id_date_planned, 3, 'Check it has been put on the purchase line also, got %d' % purchase_line_id_date_planned)

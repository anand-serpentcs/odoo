# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import AccessDenied


class WebsiteConfigSettings(models.TransientModel):
    _name = 'website.config.settings'
    _inherit = 'res.config.settings'

    def _default_website(self):
        return self.env['website'].search([], limit=1)

    website_id = fields.Many2one('website', string="website", default=_default_website, required=True)
    website_name = fields.Char('Website Name', related='website_id.name')
    language_ids = fields.Many2many(related='website_id.language_ids', relation='res.lang')
    language_count = fields.Integer(string='Number of languages', compute='_compute_language_count', readonly=True)
    default_lang_id = fields.Many2one(string='Default language', related='website_id.default_lang_id', relation='res.lang', required=True)
    default_lang_code = fields.Char('Default language code', related='website_id.default_lang_code')
    google_analytics_key = fields.Char('Google Analytics Key', related='website_id.google_analytics_key')
    google_management_client_id = fields.Char('Google Client ID', related='website_id.google_management_client_id')
    google_management_client_secret = fields.Char('Google Client Secret', related='website_id.google_management_client_secret')

    cdn_activated = fields.Boolean('Use a Content Delivery Network (CDN)', related='website_id.cdn_activated')
    cdn_url = fields.Char(related='website_id.cdn_url')
    cdn_filters = fields.Text(related='website_id.cdn_filters')
    module_website_version = fields.Boolean("A/B Testing")

    favicon = fields.Binary('Favicon', related='website_id.favicon')
    # Set as global config parameter since methods using it are not website-aware. To be changed
    # when multi-website is implemented
    google_maps_api_key = fields.Char(string='Google Maps API Key')
    has_google_analytics = fields.Boolean("Google Analytics")
    has_google_analytics_dashboard = fields.Boolean("Google Analytics in Dashboard")
    has_google_maps = fields.Boolean("Google Maps")

    @api.onchange('has_google_analytics')
    def onchange_has_google_analytics(self):
        if not self.has_google_analytics:
            self.has_google_analytics_dashboard = False
        if not self.has_google_analytics:
            self.google_analytics_key = False

    @api.onchange('has_google_analytics_dashboard')
    def onchange_has_google_analytics_dashboard(self):
        if not self.has_google_analytics_dashboard:
            self.google_management_client_id = False
            self.google_management_client_secret = False

    @api.depends('language_ids')
    def _compute_language_count(self):
        for config in self:
            config.language_count = len(self.language_ids)

    @api.model
    def get_values(self):
        if not self.user_has_groups('website.group_website_designer'):
            raise AccessDenied()
        res = super(WebsiteConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()
        res.update(
            has_google_analytics=params.get_param('website.has_google_analytics'),
            has_google_analytics_dashboard=params.get_param('website.has_google_analytics_dashboard'),
            has_google_maps=params.get_param('website.has_google_maps'),
            google_maps_api_key=params.get_param('google_maps_api_key', default=''),
        )
        return res

    def set_values(self):
        if not self.user_has_groups('website.group_website_designer'):
            raise AccessDenied()
        super(WebsiteConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param('website.has_google_analytics', self.has_google_analytics)
        self.env['ir.config_parameter'].sudo().set_param('website.has_google_analytics_dashboard', self.has_google_analytics_dashboard)
        self.env['ir.config_parameter'].sudo().set_param('website.has_google_maps', self.has_google_maps)
        self.env['ir.config_parameter'].sudo().set_param('google_maps_api_key', (self.google_maps_api_key or '').strip())

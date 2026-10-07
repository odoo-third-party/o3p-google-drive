from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    google_drive_credentials_json = fields.Text(
        string="Google Credentials JSON",
        config_parameter="o3p_google_drive.credentials_json",
        groups="base.group_system",
    )

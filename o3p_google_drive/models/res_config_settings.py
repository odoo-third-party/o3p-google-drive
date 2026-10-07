from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    google_drive_credentials_json = fields.Text(
        string="Google Credentials JSON",
        groups="base.group_system",
    )

    @api.model
    def get_values(self):
        values = super().get_values()
        values["google_drive_credentials_json"] = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("o3p_google_drive.credentials_json", "")
        )
        return values

    def set_values(self):
        result = super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            "o3p_google_drive.credentials_json",
            self.google_drive_credentials_json or "",
        )
        return result

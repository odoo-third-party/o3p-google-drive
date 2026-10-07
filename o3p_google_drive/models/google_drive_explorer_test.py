from odoo import fields, models


class GoogleDriveExplorerTest(models.Model):
    _name = "o3p.google.drive.explorer.test"
    _description = "Google Drive Explorer Test"
    _order = "name, id"

    name = fields.Char(required=True)
    google_item_id = fields.Many2one(
        "o3p.google.drive.item",
        string="Google Drive Folder",
        required=True,
        ondelete="restrict",
    )

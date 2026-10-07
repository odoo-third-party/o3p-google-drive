from odoo import models


class GoogleDriveItem(models.Model):
    _name = "o3p.google.drive.item"
    _inherit = "o3p.google.drive.folder"
    _description = "Google Drive Item"

    _gid_unique = models.Constraint(
        "UNIQUE (gid)",
        "Each Google Drive item can only be registered once.",
    )

    def _validate_google_item(self, item):
        """Items can represent any MIME type returned by Google Drive."""
        self.ensure_one()

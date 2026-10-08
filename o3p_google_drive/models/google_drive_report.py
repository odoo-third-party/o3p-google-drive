from odoo import fields, models


ANOMALY_REPORT_TYPE = "anomalies_detection"


class GoogleDriveReport(models.Model):
    _name = "o3p.google.drive.report"
    _description = "Google Drive Report"
    _order = "generated_at desc, id desc"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    item_id = fields.Many2one(
        "o3p.google.drive.item",
        string="Google Drive Item",
        index=True,
        ondelete="set null",
    )
    report_type = fields.Char(index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("error", "Error"),
        ],
        required=True,
        default="draft",
        index=True,
    )
    content = fields.Text()
    meta = fields.Json(string="Metadata", default=dict)
    generated_at = fields.Datetime(index=True)

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .google_drive_report import ANOMALY_REPORT_TYPE


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    google_drive_credentials_json = fields.Text(
        string="Google Credentials JSON",
        groups="base.group_system",
    )
    google_drive_anomaly_create_new_report = fields.Boolean(
        string="Create a new anomaly report",
    )
    google_drive_anomaly_status = fields.Selection(
        [
            ("idle", "Idle"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("done", "Completed"),
            ("failed", "Failed"),
        ],
        compute="_compute_google_drive_anomaly_status",
    )
    google_drive_anomaly_status_detail = fields.Char(
        compute="_compute_google_drive_anomaly_status",
    )
    google_drive_latest_anomaly_report_id = fields.Many2one(
        "o3p.google.drive.report",
        string="Latest anomaly report",
        compute="_compute_google_drive_anomaly_status",
    )

    @api.depends_context("uid")
    def _compute_google_drive_anomaly_status(self):
        run = self.env["o3p.google.drive.anomaly.run"].sudo().search(
            [], order="id desc", limit=1
        )
        report = self.env["o3p.google.drive.report"].sudo().search(
            [("report_type", "=", ANOMALY_REPORT_TYPE)],
            order="id desc",
            limit=1,
        )
        status = run.state if run else "idle"
        detail = (
            run._status_detail()
            if run
            else _("No Google Drive anomaly scan has been queued yet.")
        )
        for settings in self:
            settings.google_drive_anomaly_status = status
            settings.google_drive_anomaly_status_detail = detail
            settings.google_drive_latest_anomaly_report_id = report

    @api.model
    def get_values(self):
        values = super().get_values()
        values["google_drive_credentials_json"] = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_str("o3p_google_drive.credentials_json", "")
        )
        return values

    def set_values(self):
        result = super().set_values()
        self.env["ir.config_parameter"].sudo().set_str(
            "o3p_google_drive.credentials_json",
            self.google_drive_credentials_json or "",
        )
        return result

    def action_start_google_drive_anomaly_detection(self):
        self.ensure_one()
        run, started = self.env["o3p.google.drive.anomaly.run"].queue_scan(
            create_new_report=self.google_drive_anomaly_create_new_report
        )
        message = (
            _("Google Drive anomaly detection was queued.")
            if started
            else _("An anomaly scan is already queued or running.")
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Google Drive Anomaly Detection"),
                "message": message,
                "type": "success" if started else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_open_latest_google_drive_anomaly_report(self):
        self.ensure_one()
        report = self.env["o3p.google.drive.report"].sudo().search(
            [("report_type", "=", ANOMALY_REPORT_TYPE)],
            order="id desc",
            limit=1,
        )
        if not report:
            raise UserError(_("No Google Drive anomaly report exists yet."))
        return {
            "type": "ir.actions.act_window",
            "name": report.name,
            "res_model": "o3p.google.drive.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

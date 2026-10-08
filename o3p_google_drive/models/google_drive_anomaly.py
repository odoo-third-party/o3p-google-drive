import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .google_drive_report import ANOMALY_REPORT_TYPE


_logger = logging.getLogger(__name__)

ANOMALY_RUN_STATES = [
    ("queued", "Queued"),
    ("running", "Running"),
    ("done", "Completed"),
    ("failed", "Failed"),
]


class GoogleDriveAnomalyRun(models.Model):
    _name = "o3p.google.drive.anomaly.run"
    _description = "Google Drive Anomaly Detection Run"
    _order = "id desc"

    state = fields.Selection(
        ANOMALY_RUN_STATES,
        required=True,
        default="queued",
        index=True,
    )
    report_id = fields.Many2one(
        "o3p.google.drive.report",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    create_new_report = fields.Boolean(readonly=True)
    queued_at = fields.Datetime(required=True, default=fields.Datetime.now)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    anomaly_count = fields.Integer(readonly=True)
    affected_item_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.model
    def queue_scan(self, create_new_report=False):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only administrators can start anomaly detection."))

        run_model = self.sudo()
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ["o3p_google_drive_anomaly_queue"],
        )
        active_run = run_model.search(
            [("state", "in", ("queued", "running"))],
            order="id desc",
            limit=1,
        )
        if active_run:
            return active_run, False

        report_model = self.env["o3p.google.drive.report"].sudo()
        report = report_model.search(
            [("report_type", "=", ANOMALY_REPORT_TYPE)],
            order="id desc",
            limit=1,
        )
        if create_new_report or not report:
            now = fields.Datetime.now()
            report = report_model.create(
                {
                    "name": _(
                        "Google Drive Anomalies — %(date)s",
                        date=fields.Datetime.to_string(now),
                    ),
                    "report_type": ANOMALY_REPORT_TYPE,
                    "state": "draft",
                    "content": json.dumps(
                        {
                            "schema_version": 1,
                            "report_type": ANOMALY_REPORT_TYPE,
                            "runs": [],
                        },
                        indent=2,
                    ),
                    "meta": {"schema_version": 1, "run_count": 0},
                }
            )

        run = run_model.create(
            {
                "report_id": report.id,
                "create_new_report": bool(create_new_report),
            }
        )
        self.env.ref("o3p_google_drive.ir_cron_anomaly_detection").sudo()._trigger(
            coalesce=1
        )
        return run, True

    @api.model
    def _cron_process_queue(self):
        run = self.sudo().search(
            [("state", "in", ("queued", "running"))],
            order="id",
            limit=1,
        )
        if not run:
            self.env["ir.cron"]._commit_progress(remaining=0)
            return True

        if run.state == "queued":
            run.write(
                {
                    "state": "running",
                    "started_at": fields.Datetime.now(),
                    "last_error": False,
                }
            )

        try:
            with self.env.cr.savepoint():
                run._process_duplicate_names()
        except Exception as error:
            _logger.exception("Google Drive anomaly detection failed.")
            run.write(
                {
                    "state": "failed",
                    "finished_at": fields.Datetime.now(),
                    "last_error": str(error)[:4000],
                }
            )

        self.env["ir.cron"]._commit_progress(1, remaining=0)
        return True

    def _process_duplicate_names(self):
        self.ensure_one()
        anomalies = self._detect_duplicate_names()
        finished_at = fields.Datetime.now()
        affected_item_count = sum(
            len(anomaly["children"]) for anomaly in anomalies
        )
        run_values = {
            "run_id": self.id,
            "queued_at": fields.Datetime.to_string(self.queued_at),
            "started_at": fields.Datetime.to_string(self.started_at),
            "finished_at": fields.Datetime.to_string(finished_at),
            "summary": {
                "duplicate_name_groups": len(anomalies),
                "affected_item_memberships": affected_item_count,
            },
            "anomalies": anomalies,
        }
        self._append_to_report(run_values)
        self.write(
            {
                "state": "done",
                "finished_at": finished_at,
                "anomaly_count": len(anomalies),
                "affected_item_count": affected_item_count,
                "last_error": False,
            }
        )

    @api.model
    def _detect_duplicate_names(self):
        self.env.cr.execute(
            """
            WITH memberships AS (
                SELECT parent.value AS parent_gid,
                       item.name AS duplicate_name,
                       item.id AS child_id
                  FROM o3p_google_drive_item AS item
                  CROSS JOIN LATERAL jsonb_array_elements_text(
                      COALESCE(item.parent_gids, '[]'::jsonb)
                  ) AS parent(value)
                 WHERE COALESCE(item.trashed, FALSE) = FALSE
                   AND COALESCE(BTRIM(item.name), '') != ''
            )
            SELECT parent_gid,
                   duplicate_name,
                   ARRAY_AGG(child_id ORDER BY child_id) AS child_ids
              FROM memberships
             GROUP BY parent_gid, duplicate_name
            HAVING COUNT(*) > 1
             ORDER BY parent_gid, duplicate_name
            """
        )
        groups = self.env.cr.fetchall()
        if not groups:
            return []

        child_ids = {
            child_id
            for _parent_gid, _duplicate_name, group_ids in groups
            for child_id in group_ids
        }
        parent_gids = {parent_gid for parent_gid, _name, _ids in groups}
        item_model = self.env["o3p.google.drive.item"].sudo().with_context(
            o3p_google_drive_skip_auto_refresh=True
        )
        children_by_id = {
            item.id: item for item in item_model.browse(sorted(child_ids)).exists()
        }
        parents_by_gid = {
            item.gid: item
            for item in item_model.search([("gid", "in", list(parent_gids))])
        }

        anomalies = []
        for parent_gid, duplicate_name, group_ids in groups:
            parent = parents_by_gid.get(parent_gid)
            children = [
                children_by_id[child_id]
                for child_id in group_ids
                if child_id in children_by_id
            ]
            anomalies.append(
                {
                    "type": "duplicate_names_in_folder",
                    "parent": {
                        "item_id": parent.id if parent else None,
                        "gid": parent_gid,
                        "name": parent.name if parent else None,
                    },
                    "duplicate_name": duplicate_name,
                    "children": [
                        {
                            "item_id": child.id,
                            "gid": child.gid,
                            "name": child.name,
                            "mime_type": child.mime_type or "",
                        }
                        for child in children
                    ],
                }
            )
        return anomalies

    def _append_to_report(self, run_values):
        self.ensure_one()
        report = self.report_id.sudo()
        try:
            payload = json.loads(report.content or "{}")
        except (TypeError, ValueError) as error:
            raise UserError(_("The anomaly report does not contain valid JSON.")) from error
        if not isinstance(payload, dict):
            raise UserError(_("The anomaly report JSON must be an object."))
        runs = payload.setdefault("runs", [])
        if not isinstance(runs, list):
            raise UserError(_("The anomaly report JSON has an invalid runs value."))

        payload["schema_version"] = 1
        payload["report_type"] = ANOMALY_REPORT_TYPE
        payload["runs"] = [
            existing
            for existing in runs
            if not isinstance(existing, dict)
            or existing.get("run_id") != self.id
        ]
        payload["runs"].append(run_values)
        meta = report.meta if isinstance(report.meta, dict) else {}
        report.write(
            {
                "state": "ready",
                "generated_at": fields.Datetime.now(),
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
                "meta": {
                    **meta,
                    "schema_version": 1,
                    "run_count": len(payload["runs"]),
                    "last_run_id": self.id,
                    "last_anomaly_count": run_values["summary"][
                        "duplicate_name_groups"
                    ],
                },
            }
        )

    def _status_detail(self):
        self.ensure_one()
        if self.state == "queued":
            return _("Anomaly detection is queued.")
        if self.state == "running":
            return _("The cached Google Drive tree is being scanned.")
        if self.state == "failed":
            return _("Detection failed: %(error)s", error=self.last_error or "")
        return _(
            "Found %(groups)s duplicate-name groups affecting %(items)s item memberships.",
            groups=self.anomaly_count,
            items=self.affected_item_count,
        )

from fnmatch import fnmatchcase

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GoogleDriveItemAction(models.Model):
    _name = "o3p.google.drive.item.action"
    _description = "Google Drive Explorer Item Action"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    mime_type = fields.Char(
        string="MIME Type Pattern",
        required=True,
        default="*/*",
        help=(
            "MIME type matched by this action. Wildcards are supported, for example "
            "'image/*'. Use '*/*' for every item."
        ),
    )
    icon = fields.Char(
        string="Material Icon",
        default="bolt",
        help="Material Symbols icon name displayed in the explorer context menu.",
    )
    server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Server Action",
        required=True,
        ondelete="cascade",
        domain="[('model_id.model', '=', 'o3p.google.drive.item')]",
    )

    _server_action_mime_unique = models.Constraint(
        "UNIQUE (server_action_id, mime_type)",
        "A server action can only be registered once for a MIME type pattern.",
    )

    @api.constrains("server_action_id")
    def _check_server_action_model(self):
        invalid = self.filtered(
            lambda action: action.server_action_id.model_id.model
            != "o3p.google.drive.item"
        )
        if invalid:
            raise ValidationError(
                _("Explorer server actions must use the Google Drive Item model.")
            )

    def _matches_mime_type(self, mime_type):
        self.ensure_one()
        return fnmatchcase(mime_type or "", (self.mime_type or "").strip())

    @api.model
    def _get_values_by_mime_type(self, mime_types):
        mime_types = set(mime_types)
        if not mime_types or not self.has_access("read"):
            return {}

        actions = self.search([("active", "=", True)])
        return {
            mime_type: [
                {
                    "id": action.id,
                    "name": action.name,
                    "icon": action.icon or "bolt",
                }
                for action in actions
                if action._matches_mime_type(mime_type)
            ]
            for mime_type in mime_types
        }

    def _run_for_item(self, item):
        self.ensure_one()
        self.check_access("read")
        item.ensure_one()
        item.check_access("read")
        if not self.active or not self._matches_mime_type(item.mime_type):
            raise ValidationError(
                _("This explorer action is not available for the selected item.")
            )
        return self.server_action_id.with_context(
            active_model=item._name,
            active_id=item.id,
            active_ids=item.ids,
        ).run()

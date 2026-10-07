import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

GOOGLE_DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
REQUEST_TIMEOUT = 20
DEFAULT_META_MAX_AGE_SECONDS = 900


class GoogleDriveFolder(models.Model):
    _name = "o3p.google.drive.folder"
    _description = "Google Drive Folder"
    _rec_name = "name"
    _order = "id"

    gid = fields.Char(
        string="Google Drive ID",
        required=True,
        index=True,
        copy=False,
    )
    meta = fields.Json(
        string="Metadata",
        default=dict,
        copy=False,
        help=(
            "Extensible metadata envelope. The raw Google Drive item is stored under "
            "the 'item' key and its retrieval time under 'fetched_at'."
        ),
    )

    name = fields.Char(compute="_compute_virtual_fields")
    mime_type = fields.Char(compute="_compute_virtual_fields")
    parent_gids = fields.Json(compute="_compute_virtual_fields")
    created_time = fields.Datetime(compute="_compute_virtual_fields")
    modified_time = fields.Datetime(compute="_compute_virtual_fields")
    trashed = fields.Boolean(compute="_compute_virtual_fields")
    web_view_link = fields.Char(compute="_compute_virtual_fields")
    drive_id = fields.Char(compute="_compute_virtual_fields")
    meta_fetched_at = fields.Datetime(compute="_compute_virtual_fields")

    _gid_unique = models.Constraint(
        "UNIQUE (gid)",
        "Each Google Drive folder can only be registered once.",
    )

    @api.depends("gid", "meta")
    def _compute_virtual_fields(self):
        for folder in self:
            meta = folder._get_current_meta()
            item = meta.get("item") if isinstance(meta, dict) else {}
            if not isinstance(item, dict):
                item = {}

            folder.name = item.get("name") or folder.gid
            folder.mime_type = item.get("mimeType")
            folder.parent_gids = item.get("parents") or []
            folder.created_time = folder._google_datetime(item.get("createdTime"))
            folder.modified_time = folder._google_datetime(item.get("modifiedTime"))
            folder.trashed = bool(item.get("trashed"))
            folder.web_view_link = item.get("webViewLink")
            folder.drive_id = item.get("driveId")
            folder.meta_fetched_at = folder._google_datetime(meta.get("fetched_at"))

    def _get_current_meta(self):
        self.ensure_one()
        meta = self.meta if isinstance(self.meta, dict) else {}
        if not self.gid or not self._is_meta_stale(meta):
            return meta

        try:
            return self._refresh_meta()
        except Exception:
            _logger.warning(
                "Could not refresh Google Drive metadata for folder %s; using cached data.",
                self.gid,
                exc_info=True,
            )
            return meta

    def _is_meta_stale(self, meta=None):
        self.ensure_one()
        meta = meta if isinstance(meta, dict) else {}
        fetched_at = self._google_datetime(meta.get("fetched_at"))
        if not fetched_at or not isinstance(meta.get("item"), dict):
            return True
        return fields.Datetime.now() - fetched_at > timedelta(
            seconds=self._meta_max_age_seconds()
        )

    @api.model
    def _meta_max_age_seconds(self):
        value = self.env["ir.config_parameter"].sudo().get_int(
            "o3p_google_drive.meta_max_age_seconds",
            DEFAULT_META_MAX_AGE_SECONDS,
        )
        return max(0, value)

    def _refresh_meta(self):
        self.ensure_one()
        item = self._fetch_google_item()
        if item.get("mimeType") != GOOGLE_FOLDER_MIME_TYPE:
            raise UserError(
                _("Google Drive item %(gid)s is not a folder.", gid=self.gid)
            )

        meta = dict(self.meta) if isinstance(self.meta, dict) else {}
        meta.update(
            {
                "fetched_at": fields.Datetime.to_string(fields.Datetime.now()),
                "item": item,
            }
        )
        self.with_context(o3p_google_drive_refreshing_meta=True).write({"meta": meta})
        return meta

    def action_refresh_meta(self):
        for folder in self:
            folder._refresh_meta()
        return True

    def _fetch_google_item(self):
        self.ensure_one()
        access_token = self._get_google_access_token()
        response = requests.get(
            f"{GOOGLE_DRIVE_API_URL}/files/{quote(self.gid, safe='')}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "*", "supportsAllDrives": "true"},
            timeout=REQUEST_TIMEOUT,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise UserError(
                _("Google Drive could not retrieve folder %(gid)s.", gid=self.gid)
            ) from error
        return response.json()

    @api.model
    def _get_google_access_token(self):
        credentials = self._get_google_credentials()
        response = requests.post(
            credentials.get("token_uri") or GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "refresh_token": credentials["refresh_token"],
            },
            timeout=REQUEST_TIMEOUT,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise UserError(_("Google OAuth could not refresh the access token.")) from error

        access_token = response.json().get("access_token")
        if not access_token:
            raise UserError(_("Google OAuth returned no access token."))
        return access_token

    @api.model
    def _get_google_credentials(self):
        raw_credentials = self.env["ir.config_parameter"].sudo().get_str(
            "o3p_google_drive.credentials_json"
        )
        try:
            credentials = json.loads(raw_credentials or "{}")
        except (TypeError, json.JSONDecodeError) as error:
            raise UserError(_("The Google credentials setting is not valid JSON.")) from error

        required_keys = ("client_id", "client_secret", "refresh_token")
        missing_keys = [key for key in required_keys if not credentials.get(key)]
        if missing_keys:
            raise UserError(
                _(
                    "The Google credentials setting is missing: %(keys)s.",
                    keys=", ".join(missing_keys),
                )
            )
        return credentials

    @api.model
    def _google_datetime(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return False
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

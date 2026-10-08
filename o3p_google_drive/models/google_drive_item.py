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
REQUEST_TIMEOUT = 20
DEFAULT_META_MAX_AGE_SECONDS = 900
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class GoogleDriveItem(models.Model):
    _name = "o3p.google.drive.item"
    _description = "Google Drive Item"
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
    is_starting_point = fields.Boolean(
        string="Starting Point",
        default=False,
        required=True,
        help="Marks an item as a starting point for Google Drive traversal.",
    )

    name = fields.Char(index=True)
    mime_type = fields.Char()
    parent_gids = fields.Json(default=list)
    created_time = fields.Datetime()
    modified_time = fields.Datetime()
    trashed = fields.Boolean(default=False)
    web_view_link = fields.Char()
    drive_id = fields.Char()
    meta_fetched_at = fields.Datetime()
    thumbnail_ids = fields.One2many(
        "o3p.google.drive.thumbnail",
        "item_id",
        string="Thumbnails",
        readonly=True,
    )

    _gid_unique = models.Constraint(
        "UNIQUE (gid)",
        "Each Google Drive item can only be registered once.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        requested_gids = {
            values.get("gid") for values in vals_list if values.get("gid")
        }
        existing_items = self.with_context(
            o3p_google_drive_skip_auto_refresh=True
        ).search([("gid", "in", list(requested_gids))])
        existing_by_gid = {item.gid: item.id for item in existing_items}

        values_to_create = []
        new_position_by_gid = {}
        result_references = []
        for values in vals_list:
            gid = values.get("gid")
            if gid in existing_by_gid:
                result_references.append(("existing", existing_by_gid[gid]))
                continue
            if gid and gid in new_position_by_gid:
                result_references.append(("new", new_position_by_gid[gid]))
                continue

            position = len(values_to_create)
            values_to_create.append(values)
            if gid:
                new_position_by_gid[gid] = position
            result_references.append(("new", position))

        created_items = super().create(values_to_create) if values_to_create else self
        created_items._reattach_orphan_thumbnails()
        created_ids = created_items.ids
        result_ids = [
            reference
            if source == "existing"
            else created_ids[reference]
            for source, reference in result_references
        ]
        return self.browse(result_ids)

    def _reattach_orphan_thumbnails(self):
        items_by_gid = {item.gid: item for item in self if item.gid}
        if not items_by_gid:
            return
        thumbnails = self.env["o3p.google.drive.thumbnail"].sudo().search(
            [
                ("item_id", "=", False),
                ("item_gid", "in", list(items_by_gid)),
            ]
        )
        for thumbnail in thumbnails:
            thumbnail.item_id = items_by_gid[thumbnail.item_gid]

    def init(self):
        self.env.cr.execute(
            """
            ALTER TABLE o3p_google_drive_item
            ALTER COLUMN is_starting_point SET DEFAULT FALSE
            """
        )

    def read(self, fields=None, load="_classic_read"):
        self._refresh_stale_items()
        return super().read(fields=fields, load=load)

    def _refresh_stale_items(self):
        if self.env.context.get("o3p_google_drive_skip_auto_refresh"):
            return

        stale_items = self.filtered(lambda item: item._needs_api_refresh())
        if not stale_items:
            return

        try:
            access_token = self._get_google_access_token()
        except Exception:
            _logger.warning(
                "Could not obtain a Google access token while refreshing stale items.",
                exc_info=True,
            )
            return

        for item in stale_items:
            try:
                item.with_context(
                    o3p_google_drive_skip_auto_refresh=True
                )._refresh_meta(access_token=access_token)
            except Exception:
                _logger.warning(
                    "Could not refresh stale Google Drive item %s; using stored data.",
                    item.gid,
                    exc_info=True,
                )

    def _needs_api_refresh(self):
        self.ensure_one()
        meta = self.meta if isinstance(self.meta, dict) else {}
        if not self.gid or not isinstance(meta.get("item"), dict):
            return True
        if not self.write_date:
            return True
        return fields.Datetime.now() - self.write_date > timedelta(
            seconds=self._meta_max_age_seconds()
        )

    @api.model
    def _meta_max_age_seconds(self):
        value = self.env["ir.config_parameter"].sudo().get_int(
            "o3p_google_drive.meta_max_age_seconds",
            DEFAULT_META_MAX_AGE_SECONDS,
        )
        return max(0, value)

    def _refresh_meta(self, access_token=None):
        self.ensure_one()
        item = self._fetch_google_item(access_token=access_token)
        values = self._prepare_item_values(item, current_meta=self.meta)
        self.with_context(o3p_google_drive_skip_auto_refresh=True).write(values)
        return values["meta"]

    @api.model
    def _prepare_item_values(self, item, current_meta=None):
        fetched_at = fields.Datetime.now()
        meta = dict(current_meta) if isinstance(current_meta, dict) else {}
        meta.update(
            {
                "fetched_at": fields.Datetime.to_string(fetched_at),
                "item": item,
            }
        )
        return {
            "meta": meta,
            "name": item.get("name"),
            "mime_type": item.get("mimeType"),
            "parent_gids": item.get("parents") or [],
            "created_time": self._google_datetime(item.get("createdTime")),
            "modified_time": self._google_datetime(item.get("modifiedTime")),
            "trashed": bool(item.get("trashed")),
            "web_view_link": item.get("webViewLink"),
            "drive_id": item.get("driveId"),
            "meta_fetched_at": fetched_at,
        }

    def action_refresh_meta(self):
        for item in self:
            item._refresh_meta()
        return True

    def action_refresh_tree(self, generate_thumbnails=False):
        access_token = self._get_google_access_token()
        for item in self:
            meta = item._refresh_meta(access_token=access_token)
            google_item = meta.get("item", {})
            if google_item.get("mimeType") != GOOGLE_FOLDER_MIME_TYPE:
                raise UserError(
                    _(
                        "Tree refresh is only available for Google Drive folders."
                    )
                )

        self._refresh_folder_items(
            access_token,
            generate_thumbnails=generate_thumbnails,
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_refresh_children(self, generate_thumbnails=False):
        access_token = self._get_google_access_token()
        for item in self:
            meta = item._refresh_meta(access_token=access_token)
            if meta.get("item", {}).get("mimeType") != GOOGLE_FOLDER_MIME_TYPE:
                raise UserError(
                    _(
                        "Children refresh is only available for Google Drive folders."
                    )
                )

        self._refresh_immediate_children(
            access_token,
            generate_thumbnails=generate_thumbnails,
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_deeper_refresh(self):
        access_token = self._get_google_access_token()
        folder_items = self.env["o3p.google.drive.item"]

        for item in self:
            meta = item._refresh_meta(access_token=access_token)
            google_item = meta.get("item", {})
            mime_type = google_item.get("mimeType") or ""

            if mime_type == GOOGLE_FOLDER_MIME_TYPE:
                folder_items |= item
            elif mime_type.startswith("image/"):
                self.env["o3p.google.drive.thumbnail"]._refresh_image_thumbnail(
                    item,
                    google_item,
                    access_token,
                )
            elif mime_type.startswith("video/"):
                self.env["o3p.google.drive.thumbnail"]._refresh_video_thumbnail(
                    item,
                    google_item,
                    access_token,
                )
            else:
                raise UserError(
                    _(
                        "Deeper refresh is not available for MIME type %(mime_type)s.",
                        mime_type=mime_type or _("(empty)"),
                    )
                )

        folder_items._refresh_immediate_children(access_token)
        return {"type": "ir.actions.client", "tag": "reload"}

    def _refresh_immediate_children(self, access_token, generate_thumbnails=False):
        children = self.env["o3p.google.drive.item"]
        for item in self:
            item.ensure_one()
            for child_item in item._list_google_children(item.gid, access_token):
                children |= self._upsert_google_item(child_item)
        if generate_thumbnails:
            self.env["o3p.google.drive.thumbnail.job"]._enqueue_items(children)
        return True

    def _refresh_folder_items(self, access_token, generate_thumbnails=False):
        visited_gids = set()
        descendants = self.env["o3p.google.drive.item"]
        for item in self:
            descendants |= item._refresh_descendants(access_token, visited_gids)
        if generate_thumbnails:
            self.env["o3p.google.drive.thumbnail.job"]._enqueue_items(descendants)
        return True

    @api.model
    def get_explorer_folder(self, folder_id):
        folder = self.browse(int(folder_id)).exists()
        if not folder:
            raise UserError(_("The Google Drive folder no longer exists."))
        folder.check_access("read")
        if folder.mime_type != GOOGLE_FOLDER_MIME_TYPE:
            raise UserError(_("The explorer can only navigate Google Drive folders."))

        self.env.cr.execute(
            """
            SELECT id
              FROM o3p_google_drive_item
             WHERE COALESCE(trashed, FALSE) = FALSE
               AND parent_gids @> %s::jsonb
            """,
            [json.dumps([folder.gid])],
        )
        child_ids = [row[0] for row in self.env.cr.fetchall()]
        children = self.search([("id", "in", child_ids)])
        children = children.sorted(
            key=lambda item: (
                item.mime_type != GOOGLE_FOLDER_MIME_TYPE,
                (item.name or item.gid or "").casefold(),
                item.id,
            )
        )

        thumbnails = self.env["o3p.google.drive.thumbnail"].search(
            [("item_id", "in", children.ids)]
        )
        thumbnail_by_item = {thumbnail.item_id.id: thumbnail for thumbnail in thumbnails}

        return {
            "folder": self._explorer_item_values(folder),
            "items": [
                self._explorer_item_values(
                    item,
                    thumbnail=thumbnail_by_item.get(item.id),
                )
                for item in children
            ],
        }

    @api.model
    def refresh_explorer_folder(self, folder_id, generate_thumbnails=False):
        folder = self.browse(int(folder_id)).exists()
        if not folder:
            raise UserError(_("The Google Drive folder no longer exists."))
        folder.check_access("read")

        access_token = self._get_google_access_token()
        meta = folder._refresh_meta(access_token=access_token)
        if meta.get("item", {}).get("mimeType") != GOOGLE_FOLDER_MIME_TYPE:
            raise UserError(_("The explorer can only refresh Google Drive folders."))
        folder._refresh_immediate_children(
            access_token,
            generate_thumbnails=generate_thumbnails,
        )
        return True

    @api.model
    def generate_explorer_thumbnails(self, item_ids):
        items = self.browse([int(item_id) for item_id in item_ids]).exists()
        items.check_access("read")
        thumbnail_model = self.env["o3p.google.drive.thumbnail"]
        thumbnails = thumbnail_model.search([("item_id", "in", items.ids)])
        thumbnail_by_item = {thumbnail.item_id.id: thumbnail for thumbnail in thumbnails}
        supported_items = items.filtered(
            lambda item: (item.mime_type or "").startswith(("image/", "video/"))
        )
        missing_items = supported_items.filtered(
            lambda item: item.id not in thumbnail_by_item
        )
        if missing_items:
            access_token = self._get_google_access_token()
        else:
            access_token = False

        for item in missing_items:
            try:
                with self.env.cr.savepoint():
                    meta = item._refresh_meta(access_token=access_token)
                    google_item = meta.get("item", {})
                    mime_type = google_item.get("mimeType") or ""
                    if mime_type.startswith("image/"):
                        thumbnail = thumbnail_model._refresh_image_thumbnail(
                            item,
                            google_item,
                            access_token,
                        )
                    elif mime_type.startswith("video/"):
                        thumbnail = thumbnail_model._refresh_video_thumbnail(
                            item,
                            google_item,
                            access_token,
                        )
                    else:
                        continue
                    thumbnail_by_item[item.id] = thumbnail
            except Exception:
                _logger.warning(
                    "Could not generate an explorer thumbnail for Google Drive item %s.",
                    item.gid,
                    exc_info=True,
                )

        return [
            {
                "item_id": item.id,
                "thumbnail_url": (
                    f"/web/image/o3p.google.drive.thumbnail/"
                    f"{thumbnail_by_item[item.id].id}/image"
                ),
            }
            for item in supported_items
            if item.id in thumbnail_by_item
        ]

    @api.model
    def _explorer_item_values(self, item, thumbnail=None):
        meta = item.meta if isinstance(item.meta, dict) else {}
        google_item = meta.get("item") if isinstance(meta.get("item"), dict) else {}
        return {
            "id": item.id,
            "gid": item.gid,
            "name": item.name or item.gid,
            "mime_type": item.mime_type or "",
            "is_folder": item.mime_type == GOOGLE_FOLDER_MIME_TYPE,
            "web_view_link": item.web_view_link or False,
            "modified_time": fields.Datetime.to_string(item.modified_time)
            if item.modified_time
            else False,
            "size": int(google_item.get("size") or 0),
            "thumbnail_url": (
                f"/web/image/o3p.google.drive.thumbnail/{thumbnail.id}/image"
                if thumbnail
                else False
            ),
        }

    def _refresh_descendants(self, access_token, visited_gids=None):
        self.ensure_one()
        visited_gids = visited_gids if visited_gids is not None else set()
        pending_parent_gids = [self.gid]
        descendants = self.env["o3p.google.drive.item"]

        while pending_parent_gids:
            parent_gid = pending_parent_gids.pop()
            if parent_gid in visited_gids:
                continue
            visited_gids.add(parent_gid)

            for child_item in self._list_google_children(parent_gid, access_token):
                child = self._upsert_google_item(child_item)
                descendants |= child
                if (
                    child_item.get("mimeType") == GOOGLE_FOLDER_MIME_TYPE
                    and child.gid not in visited_gids
                ):
                    pending_parent_gids.append(child.gid)
        return descendants

    @api.model
    def _upsert_google_item(self, item):
        gid = item.get("id")
        if not gid:
            raise UserError(_("Google Drive returned an item without an ID."))

        existing = self.search([("gid", "=", gid)], limit=1)
        values = self._prepare_item_values(
            item,
            current_meta=existing.meta if existing else None,
        )
        if existing:
            existing.with_context(o3p_google_drive_skip_auto_refresh=True).write(values)
            return existing
        return self.with_context(o3p_google_drive_skip_auto_refresh=True).create(
            {"gid": gid, "is_starting_point": False, **values}
        )

    @api.model
    def _list_google_children(self, parent_gid, access_token):
        escaped_parent_gid = parent_gid.replace("\\", "\\\\").replace("'", "\\'")
        page_token = None
        while True:
            params = {
                "q": f"'{escaped_parent_gid}' in parents and trashed = false",
                "fields": "nextPageToken,files(*)",
                "pageSize": 1000,
                "spaces": "drive",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token

            response = requests.get(
                f"{GOOGLE_DRIVE_API_URL}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                raise UserError(
                    _(
                        "Google Drive could not list children of item %(gid)s.",
                        gid=parent_gid,
                    )
                ) from error

            response_data = response.json()
            yield from response_data.get("files", [])
            page_token = response_data.get("nextPageToken")
            if not page_token:
                break

    def _fetch_google_item(self, access_token=None):
        self.ensure_one()
        access_token = access_token or self._get_google_access_token()
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
                _("Google Drive could not retrieve item %(gid)s.", gid=self.gid)
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

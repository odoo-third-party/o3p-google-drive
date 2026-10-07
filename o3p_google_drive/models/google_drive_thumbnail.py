import io

import requests
from PIL import Image, ImageOps

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes

from .google_drive_item import REQUEST_TIMEOUT


class GoogleDriveThumbnail(models.Model):
    _name = "o3p.google.drive.thumbnail"
    _description = "Google Drive Thumbnail"
    _rec_name = "name"
    _order = "id desc"

    item_id = fields.Many2one(
        "o3p.google.drive.item",
        required=True,
        index=True,
        ondelete="cascade",
    )
    name = fields.Char(required=True, readonly=True)
    kind = fields.Selection(
        [("image", "Image"), ("video", "Video")],
        required=True,
        readonly=True,
    )
    image = fields.Image(
        string="Thumbnail",
        attachment=True,
        required=True,
        readonly=True,
    )
    mimetype = fields.Char(readonly=True)
    byte_length = fields.Integer(readonly=True)
    width = fields.Integer(readonly=True)
    height = fields.Integer(readonly=True)
    source_modified_time = fields.Datetime(readonly=True)
    refreshed_at = fields.Datetime(readonly=True)

    _item_unique = models.Constraint(
        "UNIQUE (item_id)",
        "A Google Drive item can only have one thumbnail.",
    )

    @api.model
    def _refresh_image_thumbnail(self, item, google_item, access_token):
        return self._refresh_thumbnail(item, google_item, access_token, "image")

    @api.model
    def _refresh_video_thumbnail(self, item, google_item, access_token):
        return self._refresh_thumbnail(item, google_item, access_token, "video")

    @api.model
    def _refresh_thumbnail(self, item, google_item, access_token, kind):
        item.ensure_one()
        thumbnail_link = google_item.get("thumbnailLink")
        if not thumbnail_link:
            raise UserError(
                _(
                    "Google Drive did not provide a thumbnail for %(name)s.",
                    name=item.name or item.gid,
                )
            )

        response = requests.get(
            thumbnail_link,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise UserError(
                _(
                    "Google Drive could not download the thumbnail for %(name)s.",
                    name=item.name or item.gid,
                )
            ) from error

        thumbnail, width, height = self._make_webp_thumbnail(response.content)
        values = {
            "item_id": item.id,
            "name": item.name or item.gid,
            "kind": kind,
            "image": BinaryBytes(thumbnail, filename="thumbnail.webp"),
            "mimetype": "image/webp",
            "byte_length": len(thumbnail),
            "width": width,
            "height": height,
            "source_modified_time": item.modified_time,
            "refreshed_at": fields.Datetime.now(),
        }
        existing = self.search([("item_id", "=", item.id)], limit=1)
        if existing:
            existing.write(values)
            return existing
        return self.create(values)

    @api.model
    def _make_webp_thumbnail(self, content):
        try:
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source)
                image.load()
        except Exception as error:
            raise UserError(_("The Google Drive thumbnail is not a valid image.")) from error

        output = image.copy()
        if output.width > 512 or output.height > 512:
            output.thumbnail((512, 512), Image.Resampling.LANCZOS)
        if output.mode not in ("RGB", "RGBA"):
            output = output.convert("RGBA" if "A" in output.getbands() else "RGB")

        stream = io.BytesIO()
        output.save(
            stream,
            format="WEBP",
            quality=80,
            method=6,
            optimize=True,
        )
        return stream.getvalue(), output.width, output.height

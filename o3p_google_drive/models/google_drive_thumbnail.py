import io
import logging
import os
import shutil
import subprocess
import tempfile
from urllib.parse import quote

import requests
from PIL import Image, ImageOps
from PIL import WebPImagePlugin  # noqa: F401 - registers WEBP save support

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes

from .google_drive_item import GOOGLE_DRIVE_API_URL, REQUEST_TIMEOUT


_logger = logging.getLogger(__name__)

VIDEO_HEAD_BYTES = 16 * 1024 * 1024
VIDEO_TAIL_BYTES = 4 * 1024 * 1024
THUMBNAIL_QUEUE_BATCH_SIZE = 10


class GoogleDriveThumbnail(models.Model):
    _name = "o3p.google.drive.thumbnail"
    _description = "Google Drive Thumbnail"
    _rec_name = "item_id"
    _order = "id desc"

    item_id = fields.Many2one(
        "o3p.google.drive.item",
        required=True,
        index=True,
        ondelete="cascade",
    )
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
    is_face = fields.Boolean(
        string="Face",
        default=False,
        required=True,
    )

    _item_unique = models.Constraint(
        "UNIQUE (item_id)",
        "A Google Drive item can only have one thumbnail.",
    )

    def init(self):
        self.env.cr.execute(
            """
            ALTER TABLE o3p_google_drive_thumbnail
            ALTER COLUMN is_face SET DEFAULT FALSE
            """
        )

    @api.model
    def _refresh_image_thumbnail(self, item, google_item, access_token):
        return self._refresh_thumbnail(item, google_item, access_token, "image")

    @api.model
    def _refresh_video_thumbnail(self, item, google_item, access_token):
        if not google_item.get("thumbnailLink"):
            frame = self._extract_video_frame(item, google_item, access_token)
            return self._store_thumbnail(item, frame, "video")
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

        return self._store_thumbnail(item, response.content, kind)

    @api.model
    def _store_thumbnail(self, item, image_content, kind):
        thumbnail, width, height = self._make_webp_thumbnail(image_content)
        values = {
            "item_id": item.id,
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
    def _extract_video_frame(self, item, google_item, access_token):
        if not shutil.which("ffmpeg"):
            raise UserError(_("Video thumbnail extraction requires ffmpeg."))

        with tempfile.TemporaryDirectory(prefix="o3p-drive-video-") as temp_dir:
            source_path = os.path.join(temp_dir, "source-video")
            frame_path = os.path.join(temp_dir, "frame.png")
            self._download_video_sample(
                item,
                google_item,
                access_token,
                source_path,
            )

            errors = []
            for seek_seconds in (1, 0):
                command = [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    str(seek_seconds),
                    "-i",
                    source_path,
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    frame_path,
                ]
                try:
                    result = subprocess.run(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        check=False,
                        text=True,
                        timeout=60,
                    )
                except subprocess.TimeoutExpired as error:
                    errors.append(str(error))
                    continue

                if (
                    result.returncode == 0
                    and os.path.exists(frame_path)
                    and os.path.getsize(frame_path)
                ):
                    with open(frame_path, "rb") as frame_file:
                        return frame_file.read()
                errors.append(result.stderr.strip())

        details = errors[-1][-500:] if errors and errors[-1] else _("Unknown error")
        raise UserError(
            _(
                "Could not extract a thumbnail from %(name)s: %(details)s",
                name=item.name or item.gid,
                details=details,
            )
        )

    @api.model
    def _download_video_sample(self, item, google_item, access_token, destination):
        try:
            total_size = int(google_item.get("size") or 0)
        except (TypeError, ValueError):
            total_size = 0

        head_end = VIDEO_HEAD_BYTES - 1
        head_response = self._request_video_range(
            item,
            access_token,
            f"bytes=0-{head_end}",
        )
        total_size = total_size or self._response_total_size(head_response)

        with open(destination, "wb") as video_file:
            self._write_response_range(
                head_response,
                video_file,
                offset=0,
                maximum_bytes=VIDEO_HEAD_BYTES,
            )
            if total_size > VIDEO_HEAD_BYTES:
                video_file.truncate(total_size)
                tail_start = max(VIDEO_HEAD_BYTES, total_size - VIDEO_TAIL_BYTES)
                tail_response = self._request_video_range(
                    item,
                    access_token,
                    f"bytes={tail_start}-{total_size - 1}",
                )
                if tail_response.status_code == 206:
                    self._write_response_range(
                        tail_response,
                        video_file,
                        offset=tail_start,
                        maximum_bytes=VIDEO_TAIL_BYTES,
                    )
                else:
                    tail_response.close()

    @api.model
    def _request_video_range(self, item, access_token, byte_range):
        response = requests.get(
            f"{GOOGLE_DRIVE_API_URL}/files/{quote(item.gid, safe='')}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Range": byte_range,
            },
            params={"alt": "media", "supportsAllDrives": "true"},
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise UserError(
                _(
                    "Google Drive could not download video %(name)s.",
                    name=item.name or item.gid,
                )
            ) from error

        return response

    @api.model
    def _response_total_size(self, response):
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                return int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
        try:
            return int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return 0

    @api.model
    def _write_response_range(self, response, video_file, offset, maximum_bytes):
        written = 0
        video_file.seek(offset)
        try:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if written >= maximum_bytes:
                    break
                if not chunk:
                    continue
                chunk = chunk[: maximum_bytes - written]
                video_file.write(chunk)
                written += len(chunk)
        finally:
            response.close()
        return written

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


class GoogleDriveThumbnailJob(models.Model):
    _name = "o3p.google.drive.thumbnail.job"
    _description = "Google Drive Thumbnail Queue Job"
    _order = "queued_at, id"

    item_id = fields.Many2one(
        "o3p.google.drive.item",
        required=True,
        index=True,
        ondelete="cascade",
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    queued_at = fields.Datetime(required=True, default=fields.Datetime.now)
    attempts = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)

    _item_unique = models.Constraint(
        "UNIQUE (item_id)",
        "A Google Drive item can only have one thumbnail queue job.",
    )

    @api.model
    def _enqueue_items(self, items):
        supported_items = items.filtered(
            lambda item: (item.mime_type or "").startswith(("image/", "video/"))
        )
        if not supported_items:
            return self.browse()

        jobs = self.sudo().search([("item_id", "in", supported_items.ids)])
        jobs.write(
            {
                "state": "pending",
                "queued_at": fields.Datetime.now(),
                "last_error": False,
            }
        )
        queued_item_ids = set(jobs.item_id.ids)
        jobs |= self.sudo().create(
            [
                {"item_id": item.id}
                for item in supported_items
                if item.id not in queued_item_ids
            ]
        )
        self.env.ref("o3p_google_drive.ir_cron_thumbnail_queue")._trigger(
            coalesce=1
        )
        return jobs

    @api.model
    def _process_queue(self, limit=THUMBNAIL_QUEUE_BATCH_SIZE):
        jobs = self.sudo().search(
            [("state", "in", ("pending", "processing"))],
            order="queued_at, id",
            limit=limit,
        )
        if not jobs:
            return True

        access_token = self.env["o3p.google.drive.item"]._get_google_access_token()
        thumbnail_model = self.env["o3p.google.drive.thumbnail"].sudo()
        for job in jobs:
            try:
                with self.env.cr.savepoint():
                    job.write(
                        {
                            "state": "processing",
                            "attempts": job.attempts + 1,
                            "last_error": False,
                        }
                    )
                    item = job.item_id.exists()
                    if not item:
                        job.unlink()
                    else:
                        mime_type = item.mime_type or ""
                        meta = item.meta if isinstance(item.meta, dict) else {}
                        google_item = meta.get("item", {})
                        if mime_type.startswith("image/"):
                            thumbnail_model._refresh_image_thumbnail(
                                item,
                                google_item,
                                access_token,
                            )
                        elif mime_type.startswith("video/"):
                            thumbnail_model._refresh_video_thumbnail(
                                item,
                                google_item,
                                access_token,
                            )
                        job.write({"state": "done", "last_error": False})
            except Exception as error:
                _logger.warning(
                    "Thumbnail queue job failed for Google Drive item %s.",
                    job.item_id.gid,
                    exc_info=True,
                )
                job.write(
                    {
                        "state": "failed",
                        "last_error": str(error)[:2000],
                    }
                )

            remaining = self.sudo().search_count(
                [("state", "in", ("pending", "processing"))]
            )
            seconds_left = self.env["ir.cron"]._commit_progress(
                1,
                remaining=remaining,
            )
            if not seconds_left:
                break
        return True

def migrate(cr, version):
    cr.execute(
        "ALTER TABLE o3p_google_drive_thumbnail DROP COLUMN IF EXISTS is_face"
    )

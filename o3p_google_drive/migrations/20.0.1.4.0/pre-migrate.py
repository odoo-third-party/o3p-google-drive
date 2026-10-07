def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO o3p_google_drive_item (
            gid,
            meta,
            create_uid,
            write_uid,
            create_date,
            write_date
        )
        SELECT
            gid,
            meta,
            create_uid,
            write_uid,
            create_date,
            write_date
        FROM o3p_google_drive_folder
        ON CONFLICT (gid) DO NOTHING
        """
    )

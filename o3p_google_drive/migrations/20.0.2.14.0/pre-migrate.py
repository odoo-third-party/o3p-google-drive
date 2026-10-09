def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE o3p_google_drive_item
        ALTER COLUMN custom_meta TYPE text
        USING custom_meta::text
        """
    )

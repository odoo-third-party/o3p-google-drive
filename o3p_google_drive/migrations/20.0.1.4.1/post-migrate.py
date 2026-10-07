def migrate(cr, version):
    cr.execute("DROP TABLE IF EXISTS o3p_google_drive_folder")

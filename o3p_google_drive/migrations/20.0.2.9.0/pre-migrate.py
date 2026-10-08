def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE o3p_google_drive_thumbnail
        ADD COLUMN IF NOT EXISTS item_gid VARCHAR
        """
    )
    cr.execute(
        """
        UPDATE o3p_google_drive_thumbnail AS thumbnail
           SET item_gid = item.gid
          FROM o3p_google_drive_item AS item
         WHERE item.id = thumbnail.item_id
           AND thumbnail.item_gid IS NULL
        """
    )
    cr.execute(
        """
        ALTER TABLE o3p_google_drive_thumbnail
        ALTER COLUMN item_gid SET NOT NULL,
        ALTER COLUMN item_id DROP NOT NULL,
        DROP CONSTRAINT IF EXISTS o3p_google_drive_thumbnail_item_id_fkey,
        DROP CONSTRAINT IF EXISTS o3p_google_drive_thumbnail_item_unique
        """
    )
    cr.execute(
        """
        ALTER TABLE o3p_google_drive_thumbnail
        ADD CONSTRAINT o3p_google_drive_thumbnail_item_id_fkey
        FOREIGN KEY (item_id)
        REFERENCES o3p_google_drive_item(id)
        ON DELETE SET NULL
        """
    )

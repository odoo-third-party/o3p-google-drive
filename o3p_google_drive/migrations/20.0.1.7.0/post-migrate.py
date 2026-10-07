def migrate(cr, version):
    cr.execute(
        """
        UPDATE o3p_google_drive_item
        SET name = COALESCE(meta->'item'->>'name', gid),
            mime_type = meta->'item'->>'mimeType',
            parent_gids = COALESCE(meta->'item'->'parents', '[]'::jsonb),
            created_time = CASE
                WHEN NULLIF(meta->'item'->>'createdTime', '') IS NOT NULL
                THEN (meta->'item'->>'createdTime')::timestamptz AT TIME ZONE 'UTC'
                ELSE NULL
            END,
            modified_time = CASE
                WHEN NULLIF(meta->'item'->>'modifiedTime', '') IS NOT NULL
                THEN (meta->'item'->>'modifiedTime')::timestamptz AT TIME ZONE 'UTC'
                ELSE NULL
            END,
            trashed = COALESCE((meta->'item'->>'trashed')::boolean, FALSE),
            web_view_link = meta->'item'->>'webViewLink',
            drive_id = meta->'item'->>'driveId',
            meta_fetched_at = CASE
                WHEN NULLIF(meta->>'fetched_at', '') IS NOT NULL
                THEN (meta->>'fetched_at')::timestamp
                ELSE NULL
            END
        """
    )

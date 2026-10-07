{
    "name": "O3P Google Drive",
    "summary": "Google Drive integration for Odoo.",
    "description": (
        "O3P Google Drive provides the configuration and services needed to connect "
        "Odoo with Google Drive."
    ),
    "version": "20.0.2.1.1",
    "category": "Productivity/Documents",
    "author": "O3P",
    "website": "https://github.com/odoo-third-party/o3p-google-drive",
    "license": "LGPL-3",
    "depends": ["base_setup"],
    "external_dependencies": {
        "python": ["requests", "Pillow"],
        "bin": ["ffmpeg"],
    },
    "data": [
        "security/ir.access.csv",
        "views/res_config_settings_views.xml",
        "views/google_drive_item_views.xml",
        "views/google_drive_thumbnail_views.xml",
        "views/google_drive_explorer_test_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "sequence": 1,
    "assets": {
        "web.assets_backend": [
            "o3p_google_drive/static/src/js/explorer.js",
            "o3p_google_drive/static/src/js/google_drive_explorer_field.js",
            "o3p_google_drive/static/src/xml/google_drive_explorer_field.xml",
            "o3p_google_drive/static/src/scss/google_drive_explorer.scss",
        ],
    },
}

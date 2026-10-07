{
    "name": "O3P Google Drive",
    "summary": "Google Drive integration for Odoo.",
    "description": (
        "O3P Google Drive provides the configuration and services needed to connect "
        "Odoo with Google Drive."
    ),
    "version": "20.0.1.4.0",
    "category": "Productivity/Documents",
    "author": "O3P",
    "website": "https://github.com/odoo-third-party/o3p-google-drive",
    "license": "LGPL-3",
    "depends": ["base_setup"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.access.csv",
        "views/res_config_settings_views.xml",
        "views/google_drive_item_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "sequence": 0,
}

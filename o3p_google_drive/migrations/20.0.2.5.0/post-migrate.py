from odoo import SUPERUSER_ID, api


REMOVED_XML_IDS = (
    "menu_o3p_google_drive_explorer_test",
    "action_google_drive_explorer_test",
    "google_drive_explorer_test_view_form",
    "google_drive_explorer_test_view_list",
    "access_o3p_google_drive_explorer_test_system",
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    model_data = env["ir.model.data"]

    for name in REMOVED_XML_IDS:
        external_id = model_data.search(
            [("module", "=", "o3p_google_drive"), ("name", "=", name)],
            limit=1,
        )
        if not external_id:
            continue
        record = env[external_id.model].browse(external_id.res_id).exists()
        if record:
            record.unlink()
        external_id.unlink()

    cr.execute("DROP TABLE IF EXISTS o3p_google_drive_explorer_test")
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.model.fields'
           AND res_id IN (
               SELECT id FROM ir_model_fields WHERE model = %s
           )
        """,
        ["o3p.google.drive.explorer.test"],
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.model'
           AND res_id IN (
               SELECT id FROM ir_model WHERE model = %s
           )
        """,
        ["o3p.google.drive.explorer.test"],
    )
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model = %s",
        ["o3p.google.drive.explorer.test"],
    )
    cr.execute(
        "DELETE FROM ir_model WHERE model = %s",
        ["o3p.google.drive.explorer.test"],
    )

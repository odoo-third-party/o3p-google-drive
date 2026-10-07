# O3P Google Drive

Google Drive integration addon for Odoo 20.

The first version adds a **Google Drive** section to the Odoo Settings app. System
administrators can store the OAuth `type`, `client_id`, `client_secret`, and
`refresh_token` together as JSON.

## Deployment

The deployment scripts target the same Odoo 20 instance as the Persona addon:

- `./restart_odoo20.sh` pulls or bootstraps the deployment checkout, links the
  addon into `/opt/odoo20/addons`, clears Python caches, and restarts Odoo.
- `./upush.sh "commit message"` commits and pushes the current branch, then
  optionally runs the restart script.
- `./fulldeploy.sh "commit message"` commits, pushes, deploys, and automatically
  installs or upgrades `o3p_google_drive` on `persona.standalone.io`.

Paths, service names, database names, and users can be overridden through the
environment variables declared at the top of each script.

---
paths:
  - "compose.production.yml"
  - "docker-compose.yml"
  - "**/Dockerfile*"
  - "frontend/nginx.production.conf.template"
  - "deploy/**"
  - "docs/**"
  - ".github/**"
---
# Deployment and release operations

Read `deploy/linux/README.md` for Ubuntu and `docs/github-deployment.md` for releases.
Use a separate Compose project and disposable volume for smoke tests. Never run
`down -v`, test restoration, or table-dropping tests against the production project.
Back up before schema or retention changes; verify rollback compatibility.

Production uses the existing HTTPS reverse proxy and an internal HTTP listener.
Keep PostgreSQL and backend ports unpublished. Preserve Nginx source restrictions,
exact trusted proxy addresses, same-origin routing, and React route fallback.
Changing the Docker subnet requires updating both static service IPs and trusted
proxy settings. Docker published ports can bypass host UFW rules; preserve the
application/network source restrictions. Never disable TLS verification to work
around certificate inspection; configure the organization's verified CA instead.

The dashboard Web application OAuth client is separate from the Chrome Extension
OAuth client. `ADMIN_EMAILS` is a comma-separated exact allowlist, constrained by
Workspace domains. Do not change live auth modes or allowlists merely to pass tests.
A new database does not inherit collection policy from an old deployment.

GitHub Actions signs extension packages and publishes versioned Release assets
before advertising them through Pages. Keep signing material in the configured
secret, never in Git or artifacts. Verify anonymous CRX download, checksum, package
identity, OAuth client and update feed. Do not overwrite a released version or
assume HTTP download success proves managed Chrome installation/enrollment.

Jamf install settings share `com.google.Chrome` with other extensions. Merge the
history extension entry without removing the Eaglercraft blocker. Managed extension
settings use their separate extension preference domain. Start with a pilot device.
Publishing source, publishing an extension update, and changing device scope are
separate operations; perform only the operations authorized by the user.

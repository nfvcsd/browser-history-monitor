# Ubuntu VM: fresh production deployment

Prepared for VM `10.140.1.32`, existing TLS reverse proxy `10.140.1.2`, and public
proxy address `74.81.167.39`. This starts an empty database; nothing is copied from
the Mac. The repository's original `docker-compose.yml` remains development-only.
Use the standalone `compose.production.yml` below, without combining the two files.

## 1. Prepare configuration

Install Docker Engine and the Compose plugin using
[Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
Then on the VM:

```sh
cd /opt/browser-history-monitor
git pull --ff-only
cp deploy/linux/env.production.example .env.production
chmod 600 .env.production
openssl rand -hex 32
nano .env.production
```

Paste that generated hex password into `POSTGRES_PASSWORD`. Set `GOOGLE_CLIENT_ID`
to your dashboard **Web application** OAuth client, which is separate from the
already populated Chrome Extension OAuth client. The existing Mac `.env` contains
the dashboard client ID if you want to reuse it. Preserve the provided IPs and
review the administrator/domain allowlists.

In Google Auth Platform, add `https://history.nfv.k12.ia.us` to the dashboard Web
client's **Authorized JavaScript origins**. The existing dashboard uses Google
Identity Services credentials, so this does not require an OAuth redirect route.
Do not paste the Chrome Extension client into `GOOGLE_CLIENT_ID`.

The production file forces Google admin login and enrolled extension auth. No
shared development tokens are accepted. `.env.production` is ignored by Git.
Use a hexadecimal database password as above; other characters would need URL
encoding in the database connection URL. Changing this password after PostgreSQL
initializes does not change the database role's stored password.

## 2. Configure DNS and your existing reverse proxy

- Public DNS: `history.nfv.k12.ia.us` → `74.81.167.39`, if that is the proxy's
  inbound public address. Internal DNS may point the hostname to `10.140.1.2`.
- Valid HTTPS certificate for `history.nfv.k12.ia.us` on the existing proxy.
- Upstream scheme **HTTP**, host **10.140.1.32**, port **8080**.
- Forward all paths without stripping `/api/`. The same origin serves dashboard
  pages and API calls; no Vite development server or separate API hostname is used.
- Preserve `Host`, set `X-Forwarded-Proto` to `https`, and set `X-Forwarded-For` to
  the actual client IP. Do not blindly trust a client-supplied forwarded-IP header.
- Permit request bodies up to **10 MB** and a **120-second** upstream timeout.
- Disable proxy caching for API requests; do not log authorization headers or
  request bodies. Prefer an access log without query strings for this app.

For a single edge Nginx proxy, the location settings are:

```nginx
location / {
    proxy_pass http://10.140.1.32:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
    client_max_body_size 10m;
    proxy_read_timeout 120s;
}
```

Keep these inside your existing HTTPS virtual host, which supplies the certificate.
If another load balancer is in front of the edge proxy, resolve the actual client
address there using explicitly trusted peers first.

Allow VM TCP 8080 only from `10.140.1.2` at the network firewall. The application
Nginx also enforces this source restriction, even where Docker publishing bypasses
host UFW rules. Keep SSH restricted to administration hosts. Do not expose database
port 5432 or backend port 8000; the Compose file does not publish them.

The container proxy uses `172.30.32.2` on `172.30.32.0/24`. Confirm this subnet does
not overlap existing VM/Docker/VPN routes. If it does, change the Compose subnet,
frontend static IP, and backend trusted proxy entry together. The backend trusts
only this gateway and the edge proxy `10.140.1.2`, not the public IP or entire LAN.

## 3. Start the fresh stack

```sh
sudo docker compose --env-file .env.production -f compose.production.yml config --quiet
sudo docker compose --env-file .env.production -f compose.production.yml up -d --build
sudo docker compose --env-file .env.production -f compose.production.yml ps
sudo docker compose --env-file .env.production -f compose.production.yml logs --tail=100 backend
```

The production project is named `history-production`, with a separate persistent
PostgreSQL volume. The backend creates its tables at startup. Do not run multiple
backend replicas: the application currently performs startup table creation and
retention maintenance internally, rather than through a separate migration/job system.

From the **reverse proxy host**:

```sh
curl -f http://10.140.1.32:8080/health
```

Then visit `https://history.nfv.k12.ia.us/health` and the dashboard in a browser.
Expect health `{"status":"ok"}` and Google sign-in. This health endpoint confirms
API responsiveness, not a full database transaction. Verify the Settings page loads
after sign-in as a database-backed check. A direct request from an unapproved LAN
machine should return 403. If your proxy uses a different source interface, confirm
its actual address before changing the allowlist.

Configure retention, school timezone, schedule, and IP rules before adding pilot
devices. A fresh database uses default collection rules; prior Mac settings are
not migrated. Do not assume the proxy's public IP `74.81.167.39` is also the school
client egress IP. Check the actual pilot client IP before setting an allowlist.

Force-install the released extension on one pilot Mac using the Jamf payloads in
`deploy/`. Confirm verified enrollment, a successful upload, time measurements,
and schedule/IP enforcement. Silent Google OAuth still requires this real-device
pilot; an installation alone is not proof of enrollment.

## 4. Backup and recovery

Create daily PostgreSQL dumps and copy them to protected storage outside this VM.
Back up `.env.production` securely as well. A VM snapshot alone is not a tested
database recovery procedure. Example manual backup:

```sh
mkdir -p backups
chmod 700 backups
(umask 077; sudo docker compose --env-file .env.production -f compose.production.yml exec -T db \
  pg_dump -U browser_history -d browser_history -Fc > "backups/history-$(date +%Y%m%d-%H%M%S).dump")
```

Verify the command succeeds and the dump is nonempty before copying it off-host.
Test restoration into a separate empty PostgreSQL 17 database using `pg_restore
--no-owner --no-acl --exit-on-error`. Never test restoration against the live database.
Dumps contain browsing history and enrollment/policy information: restrict access.

For application updates, take a backup, record the deployed Git commit, pull the
reviewed revision, then repeat `up -d --build`. Reverting to an earlier code revision
is only safe when its database schema is compatible; otherwise restore into a
separate recovery stack and validate before cutover. Never use `down -v` on this
production stack: it deletes the database volume.

## Certificate-inspecting networks

A clean backend build on the development network encountered `CERTIFICATE_VERIFY_FAILED`
when pip contacted PyPI. If your VM network also inspects HTTPS, install your
organization's verified inspection CA in the VM and the container build/runtime
trust stores, or arrange an inspection exemption for the required package and
Google identity endpoints. Do not use `--trusted-host`, `curl -k`, or disable TLS
verification. This is a network trust problem, not a missing FastAPI package.

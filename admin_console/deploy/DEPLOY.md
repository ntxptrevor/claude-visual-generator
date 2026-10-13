# NTXP Admin Console: Deployment

**Target:** `https://admin.ntxpllc.com` on the NTXP Hostinger VPS, as a Docker Manager project.
**Who can sign in:** exactly `trevor@ntxpllc.com` and `alison@ntxpllc.com`.
**Change class:** creating the project, editing its environment, and DNS are **Tier 3**.
Explain the exact change and wait for owner approval before running each one.

## Architecture

```
Browser ──HTTPS──> [existing VPS reverse proxy  OR  caddy (profile "tls")]
                          │
                          ▼
                 oauth2-proxy :4180   Google sign-in, allow-list = emails.txt
                          │  sets X-Forwarded-Email
                          ▼
                 app :8080 (no published port)   FastAPI; re-checks owner email
```

| File | Purpose |
|---|---|
| `docker-compose.yaml` (repo root) | **Used by Hostinger.** Builds the app from the GitHub URL; allow-list and Caddyfile are inlined. |
| `admin_console/deploy/docker-compose.yaml` | Same stack for a local clone (`docker compose -f ... up`). Uses the files below. |
| `admin_console/deploy/Dockerfile` | python:3.11-slim, non-root, `uvicorn admin_console.server.app:app` on 8080, TCP health check. |
| `admin_console/deploy/emails.txt` | The two owner emails. Keep the root compose `owner_emails` block identical. |
| `admin_console/deploy/Caddyfile` | HTTPS for `admin.ntxpllc.com`, used only with the `tls` profile. |
| `admin_console/deploy/.env.example` | Every variable, placeholders only. |

**Allow-list note:** `--email-domain` is intentionally not set. oauth2-proxy admits an email that matches the domain *or* the file, so `--email-domain=ntxpllc.com` would let every NTXP account in. The Internal OAuth client already limits sign-in to the ntxpllc.com Workspace. The app then re-checks the owner list itself.

**Prerequisites**
- **Google access layer** is set up once per org (`scripts/google_workspace/README.md`). The VPS needs **key mode** (`NTXP_GOOGLE_SA_KEY`), because keyless mode needs a gcloud login the container does not have.
- **Admin DB sheet** exists and its ID is known (`NTXP_ADMIN_DB_SHEET_ID`).
- **Hostinger:** read the run journal (`hostinger-run-journal.json`) first for the VPS ID, known defects and which tier to start at.
- **Docker Compose 2.24 or newer** on the VPS (needed for inline `configs` and optional `env_file`).

---

## (a) Create the Google OAuth web client

1. **Open** Google Cloud Console, project `ntxp-workspace-agent`, signed in as a Workspace admin.
2. **OAuth consent screen** (APIs & Services > OAuth consent screen):
   - **User type:** Internal.
   - **App name:** NTXP Admin Console. **Support email:** trevor@ntxpllc.com.
   - **Scopes:** `openid`, `email`, `profile` only.
3. **Credentials** > Create credentials > OAuth client ID:
   - **Application type:** Web application. **Name:** NTXP Admin Console.
   - **Authorized JavaScript origins:** `https://admin.ntxpllc.com`
   - **Authorized redirect URIs:** `https://admin.ntxpllc.com/oauth2/callback` (exact; https; no trailing slash).
4. **Copy** the Client ID and Client secret straight into the vault (step c). Do not paste them into chat or email.

## (b) Generate the cookie secret

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # prints exactly 32 characters
```

- **Use** the output as `OAUTH2_PROXY_COOKIE_SECRET`.
- **Rotating** it signs everyone out. That is the expected result.

## (c) Store secrets

1. **NTXP vault** (source of truth). Add one entry per value in `.env.example`, at minimum:
   - `OAUTH2_PROXY_CLIENT_ID`, `OAUTH2_PROXY_CLIENT_SECRET`, `OAUTH2_PROXY_COOKIE_SECRET`
   - `NTXP_GOOGLE_SA_KEY`, `NTXP_GOOGLE_ADMIN_SUBJECT`, `NTXP_GOOGLE_MAPS_KEY`
   - `NTXP_ADMIN_DB_SHEET_ID`, `NTXP_COUNCIL_URL`, `NTXP_COUNCIL_SHEET_ID`
   - `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `JOBTREAD_GRANT_KEY`, `NTXP_JOBTREAD_ORG_ID`, `PLAUD_API_KEY`
   - `QBO_ACCESS_TOKEN`, `QBO_REALM_ID` (if QuickBooks checks are wanted)
   - `QUO_API_KEY`, `QUO_FROM_NUMBER`, `NTXP_ALISON_SMS`, `NTXP_TREVOR_SMS`, `NTXP_ALERT_SENDER`
   - `NTXP_PROJECT_ASSIGNMENTS`, `NTXP_OFFICE_EMAILS`
2. **Build the project environment** as `KEY=VALUE` lines, one per variable, from the vault:
   - `NTXP_ADMIN_DEMO=false` in production.
   - `NTXP_GOOGLE_SA_KEY` on one line; keep the `\n` sequences inside `private_key` as typed characters.
   - `COMPOSE_PROFILES=tls` **only** if step (d) finds no existing reverse proxy.
3. **Never** put a real value in the repo, the compose files, a commit, a ticket or chat. The repo is public. `.env` and `admin_console/deploy/.env` are git-ignored.

## (d) Hostinger: find the VPS, choose the proxy path, create the project

Use the Hostinger tier ladder (MCP > direct REST > hPanel in Chrome > LMCP > SSH). Two failures on a tier means descend. Log the outcome in the run journal.

1. **Find the VPS:** `account_ids.virtual_machine_id` in the journal, or the connector's VPS list operation (find it with the connector's `search` for "virtual machines"; do not guess tool names). Note `virtualMachineId` and the public **IPv4**.
2. **Look for an existing reverse proxy:**
   - `VPS_getProjectListV1 { virtualMachineId }`, then `VPS_getProjectContentsV1` on each project.
   - A proxy exists if any project runs Caddy, Traefik, nginx or nginx-proxy-manager **publishing 80/443** (the MCP gateway at `mcp.ntxpllc.cloud` sits behind one).
   - If unsure, SSH: `sudo ss -ltnp | grep -E ':(80|443) '`.
3. **Choose the path:**

   | Situation | Do this |
   |---|---|
   | **Existing proxy terminates TLS** (expected on this VPS) | Do **not** set `COMPOSE_PROFILES=tls`. Add a site for `admin.ntxpllc.com` to that proxy (below). |
   | **Nothing on 80/443** | Set `COMPOSE_PROFILES=tls`. Caddy gets the certificate on its own once DNS points at the VPS. |

   **Routing through the existing proxy:**
   - **Proxy runs on the host** (not in Docker): upstream `http://127.0.0.1:4180` (default bind).
   - **Proxy runs in Docker:** set `OAUTH2_PROXY_BIND_ADDR=172.17.0.1` (the Docker bridge; reachable from containers, not from the internet) and use upstream `http://172.17.0.1:4180`. Confirm the VPS firewall does not open 4180 publicly.
   - **Site settings:** pass `Host` through, set `X-Forwarded-Proto https`, and turn off response buffering (SSE live tiles). Example, Caddy: `admin.ntxpllc.com { reverse_proxy 172.17.0.1:4180 { flush_interval -1 } }`. nginx: `proxy_buffering off;`.
   - **Warn first:** reloading the shared proxy can drop the Hostinger MCP connector mid-call.
4. **Create the project** (Tier 3: state VPS, project name, repo and proxy choice; wait for approval):

   ```
   VPS_createNewProjectV1 {
     virtualMachineId: <id>,
     project_name: "ntxp-admin",
     content: "https://github.com/ntxptrevor/claude-visual-generator",
     environment: "<KEY=VALUE lines from step c>"
   }
   ```
   - Hostinger resolves the repo-root `docker-compose.yaml`; the app image builds from the GitHub URL at `NTXP_ADMIN_GIT_REF` (default `master`).
   - If the repository is ever made private, the URL build context will fail. Clone on the VPS and switch `build.context` to `.`.
5. **Watch it start:** `VPS_getProjectContainersV1` until `app` and `oauth2-proxy` (and `caddy` with `tls`) are running. On failure read `VPS_getProjectLogsV1` and use the runbook (RB-016, RB-017, RB-021).

## (e) DNS: `admin` A record (Tier 3, owner approval)

DNS on ntxpllc.com carries company mail. Use the full chain every time. **`overwrite` stays `false`.**

1. **Read:** `DNS_getDNSRecordsV1 { domain: "ntxpllc.com" }`. Confirm there is no `admin` record (if one exists, stop and ask).
2. **Snapshot:** `DNS_getDNSSnapshotListV1 { domain: "ntxpllc.com" }`. Write down the newest `snapshotId` as the rollback point.
3. **Validate** (returns 422 on a bad zone; nothing changes):
   ```
   DNS_validateDNSRecordsV1 {
     domain: "ntxpllc.com", overwrite: false,
     zone: [{ name: "admin", type: "A", ttl: 300, records: [{ content: "<VPS IPv4>" }] }]
   }
   ```
4. **State the diff** for approval: "Add A record admin.ntxpllc.com → <VPS IPv4>, TTL 300. No other record changes. Rollback: snapshot <id>." Wait for an owner to approve.
5. **Update:** `DNS_updateDNSRecordsV1` with the identical payload (`overwrite: false`).
6. **Verify:** re-run `DNS_getDNSRecordsV1`, then from a shell `dig +short admin.ntxpllc.com @8.8.8.8` must print the VPS IP. Do not declare success from the API response alone.
7. **Never** touch MX, NS, SPF/DKIM/DMARC, the apex, or `mcp.ntxpllc.cloud` records in this change.

## (f) Verify

| Check | How | Pass |
|---|---|---|
| **TLS** | Open `https://admin.ntxpllc.com` | Valid certificate, Google sign-in button |
| **Trevor** | Sign in as trevor@ntxpllc.com | Console loads; `/api/me` shows trevor |
| **Alison** | Sign in as alison@ntxpllc.com (private window) | Console loads; `/api/me` shows alison |
| **Third account** | Sign in with any other @ntxpllc.com account | oauth2-proxy **403**, console never loads |
| **Outside account** | Personal Gmail | Google blocks it (Internal app) |
| **Health** | Signed in, open `https://admin.ntxpllc.com/api/health` | JSON with `sources`; Google sources `ok`; `"demo": false` |
| **Header spoof** | `curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Email: alison@ntxpllc.com' https://admin.ntxpllc.com/api/me` | Not 200 (sign-in page) |
| **App not exposed** | `curl -m 5 http://<VPS IPv4>:8080/` and `:4180/` | Both time out or refuse |
| **Live tiles** | Analytics page, click Run analysis now | Tiles update without reload |

Record the result, date and commit in the Hostinger run journal.

## (g) Rollback

| Problem | Action | Tier |
|---|---|---|
| **Bad release** | Set `NTXP_ADMIN_GIT_REF` to the last good commit SHA in the project environment, then re-run step (d)4 with the same project name to rebuild. | 3 |
| **Container misbehaving** | `VPS_restartProjectV1 { virtualMachineId, projectName: "ntxp-admin" }` (keeps volumes). | 2 |
| **Take the console offline** | `VPS_stopProjectV1`. Nothing else on the VPS is affected. | 3 |
| **Remove completely** | `VPS_deleteProjectV1`, then remove the proxy site block (if used). | 3 |
| **DNS** | Inspect with `DNS_getDNSSnapshotV1`, then `DNS_restoreDNSSnapshotV1 { domain: "ntxpllc.com", snapshotId }` from step (e)2. Re-verify MX and the website. | 3 |
| **Suspected secret leak** | Stop the project, rotate the OAuth secret, cookie secret and any exposed key (runbook RB-009), update vault + environment, start. | 3 |

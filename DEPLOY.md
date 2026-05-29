# Deploying Doppel (single-user VPS)

v1 runs the whole stack — Postgres + Redis + the FastAPI API + the ARQ worker — on one small VPS
(target: **Hetzner CX32**, 4 vCPU / 8 GB / amd64). The image is **built on the box** (not
cross-built): it carries the CPU PyTorch stack (~2.2 GB), and QEMU-cross-building multi-GB torch is
brutally slow.

**Access model.** The API is **not** exposed publicly — it binds to `127.0.0.1` and you reach it
over an SSH tunnel. Postgres/Redis publish no host ports at all (compose-network only). There is no
auth or TLS in v1 (a Non-Goal); a public, authenticated edge is the separate Phase-C hardening pass.
The security boundary is the SSH-gated VPS, not the app.

**Security invariants — do not violate (the deploy's safety rests on these):**
- **Always run with *both* compose files** (the `dc` alias below bakes them in). **Never** run bare
  `docker compose up` / base-only on the VPS: the dev base initializes Postgres with the *public* dev
  password `doppel`, and Docker writes its own iptables rules that **bypass `ufw`** — so a base-only
  run could expose a trivial-password DB to the internet, firewall notwithstanding. (The base also
  binds its dev ports to `127.0.0.1` as a backstop, but the rule stands.)
- **Postgres and Redis never publish public host ports.** The overlay publishes none — keep it so.
- **The API stays bound to `127.0.0.1`, reached only via SSH tunnel.** `/recommend` is
  **unauthenticated** and spends Anthropic budget + hits MusicBrainz (IP-block risk), so it must never
  be exposed publicly (no public bind, no reverse proxy) until app auth **and** inbound rate limiting
  exist (Phase C). There is no TLS in v1 — the SSH tunnel is the transport encryption.
- **Secrets live only in the host `.env`** (`chmod 600`, never committed). Never paste a real `.env`
  or a rendered `docker compose config` (it expands secrets) into logs, issues, handoff notes, or chat.

Everything below uses the **production overlay** (`docker-compose.prod.yml`) layered on the base
file. Define a shell alias for the repeated prefix and reuse it throughout:

```bash
echo "alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'" >> ~/.bashrc
source ~/.bashrc
```

---

## 1. Provision the server

- Create a **Hetzner CX32** (amd64), image **Ubuntu 24.04 LTS**, and attach your SSH public key at
  create time. No DNS/domain is needed — access is via SSH tunnel.
- Note the server's IP. Initial login is `ssh root@<vps-ip>`.

## 2. Harden the box

As `root` on first login, create a non-root sudo user and lock down SSH:

```bash
adduser deploy                                  # set a password
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy   # copy your authorized key over

# Disable password + root SSH login (key-only)
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall: allow SSH only. The API port is NEVER opened — it's loopback-only.
ufw allow OpenSSH
ufw --force enable

# Auto-apply security updates, and ban repeated SSH auth failures (key-only already defeats brute
# force; fail2ban sheds scanner noise + adds a layer).
apt-get update && apt-get install -y unattended-upgrades fail2ban
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  > /etc/apt/apt.conf.d/20auto-upgrades
printf '[sshd]\nenabled = true\n' > /etc/fail2ban/jail.d/sshd.local
systemctl enable --now fail2ban
```

Reconnect as `ssh deploy@<vps-ip>` for the rest of this guide.

## 3. Install Docker + the Compose plugin

Docker's official apt repo (Compose v2.24+ is required for the overlay's `!reset`/`!override` tags):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker deploy        # run docker without sudo; log out/in for this to take effect
```

Log out and back in, then sanity-check: `docker compose version` (expect v2.24+).

## 4. Clone and configure

```bash
cd ~
git clone <repo-url> doppel
cd doppel

cp .env.example .env
# Generate a strong DB password. It's handed to asyncpg as a discrete connection argument (never
# interpolated into a URL), so any value is safe; `-hex` is just a clean, quoting-safe default.
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" >> .env
```

Then edit `.env` and fill in the real secrets:
- `LASTFM_API_KEY` — cultural recall (degrades gracefully if blank).
- `ANTHROPIC_API_KEY` — LLM rationales (degrade to no-rationale if blank). **Use a VPS-dedicated key,
  separate from your local dev key**, so a VPS compromise never forces rotating the dev key too; set a
  spend limit on it.
- `POSTGRES_PASSWORD` — appended above; confirm it's set (the prod overlay **fails fast** if it
  isn't). It reaches the app/worker/migrate as a discrete asyncpg argument (`DB_PASSWORD`), so it may
  contain any characters.

Lock it down — it holds your Anthropic + DB secrets:

```bash
chmod 600 .env
```

`.env` is gitignored and lives only on the host — never commit it, and never paste a real `.env` or a
rendered `docker compose config` (it expands secrets) into logs, issues, handoff notes, or chat.

## 5. Build the image on the VPS

```bash
dc --profile app build           # amd64, ~2.2 GB, a few minutes on a CX32
```

## 6. Apply migrations (explicit one-shot — Invariant #3)

Migrations are forward-only and run as their own step, never from the app/worker entrypoint:

```bash
dc run --rm migrate              # starts Postgres, applies 0001/0002…, exits 0
```

`up` (next step) also gates app/worker on this completing, but run it explicitly first so a schema
failure surfaces on its own rather than buried in startup.

## 7. Start the stack

```bash
dc --profile app up -d
dc ps                            # postgres/redis/app/worker Up; migrate Exited (0)
```

## 8. Verify (over the SSH tunnel)

From **your laptop**, open a tunnel and hit the API on loopback:

```bash
ssh -L 8000:localhost:8000 deploy@<vps-ip>      # leave this open
# in another local shell:
curl -s localhost:8000/health                   # {"status":"ok",...}
curl -s -X POST localhost:8000/recommend \
  -H 'content-type: application/json' \
  -d '{"seed_title":"Take Five","seed_artist":"The Dave Brubeck Quartet"}'
```

A cold seed returns `202` + a `job_id`; poll it until terminal — `succeeded` with results, or
`failed`. Quote the URL so the shell doesn't glob the handle:
```bash
curl -s "localhost:8000/recommend/<job_id>"
```
(The first cold query is MB-bound — expect up to ~N×7 s where N is `RESOLVE_CANDIDATE_LIMIT`; the
corpus is then seeded, so a repeat of the same/overlapping seed returns warm in seconds.)

## 9. Daily backups (pg_dump cron)

`scripts/backup_db.sh` dumps the DB from inside the Postgres container to a timestamped, compressed
`-Fc` archive on the host and prunes to the most-recent `KEEP` (default 7). Create the backup dir,
then add a cron entry:

```bash
mkdir -p ~/doppel-backups
( crontab -l 2>/dev/null; \
  echo "30 3 * * * /usr/bin/env bash /home/deploy/doppel/scripts/backup_db.sh >> /home/deploy/doppel-backups/backup.log 2>&1" ) \
  | crontab -
```

Test it once immediately: `bash ~/doppel/scripts/backup_db.sh` (writes to `~/doppel-backups`). If
cron can't find `docker`, prepend `PATH=/usr/local/bin:/usr/bin:/bin` to the crontab.

The local cron alone recovers from app-level corruption, but the archives live on the same VPS
volume as the live DB — a volume loss, server seizure, or vendor incident takes both. The next
sub-section wires an off-box mirror for real disaster recovery.

### 9.1 Off-box mirror via rclone (recommended: Cloudflare R2)

`scripts/backup_db.sh` mirrors each new archive to an rclone remote when `BACKUP_REMOTE` is set,
and prunes off-box copies past `OFFSITE_KEEP_DAYS` (default 30). The script is provider-agnostic
(any rclone backend works); the worked example below is **Cloudflare R2** (S3-compatible, free
egress — the restore path costs nothing — ~$0.015/GB/mo storage) with **client-side encryption**
via rclone's `crypt` wrapper, so the provider sees only ciphertext.

**1. Install rclone on the VPS — use the official install script, not apt.**

```bash
sudo apt-get remove -y rclone 2>/dev/null || true   # detach any dpkg-tracked binary first
curl https://rclone.org/install.sh | sudo bash
rclone version                                       # expect ≥ v1.65
dpkg -S "$(command -v rclone)" 2>/dev/null \
    && echo "WARN: rclone is dpkg-tracked, apt could clobber it" \
    || echo "OK: rclone is not dpkg-tracked"
```

Ubuntu 24.04's apt ships rclone v1.60 (late 2022), which predates two R2-specific fixes
in v1.65+: older rclone sends `X-Amz-Acl: private` headers R2 doesn't implement (501),
and HEADs uploaded objects with `?versionId=` queries R2 also doesn't implement (501).
The `apt-get remove` first matters even if rclone wasn't apt-installed yet (it's a no-op
when the package isn't present): `install.sh` overwrites `/usr/bin/rclone` but does NOT
touch the dpkg registration, so a previously-apt-installed `rclone` would silently get
downgraded back to v1.60 by any future `apt upgrade` or `unattended-upgrades` pass —
breaking off-box backups. The final `dpkg -S` check verifies the binary isn't
dpkg-tracked (expect the OK line). Cron's default PATH (`/usr/bin:/bin`) finds the new
binary without further config.

A third R2 quirk — rclone's S3 default of checking/creating the bucket before each write,
which an Object R&W token can't do — is **not** fixed by the upgrade and needs explicit
config (step 4 below).

**2. Create the R2 bucket + bucket-scoped API token.** In the Cloudflare dashboard → **R2**:
- Create a bucket, e.g. `doppel-backups`.
- **Manage R2 API Tokens** → new token, permission **Object Read & Write**, scoped to that bucket
  only (so a token leak can't touch other R2 buckets or the rest of your account).
- Note the **Access Key ID**, **Secret Access Key**, and the **S3 API endpoint** for your account
  (`https://<accountid>.r2.cloudflarestorage.com`).

**3. Configure two rclone remotes** — `r2-base` (the raw R2 backend) wrapped by `r2-crypt`
(client-side encryption). Run `rclone config` and step through `n` (new remote) twice:

For **`r2-base`**: storage `s3`; provider `Cloudflare`; paste the access key ID + secret + the R2
endpoint from step 2; leave region / location constraint blank; accept other defaults.

For **`r2-crypt`**: storage `crypt`; remote `r2-base:doppel-backups/encrypted` (any sub-path inside
the bucket); filename + directory name encryption **standard** (both encrypted); password — type a
strong one (or `openssl rand -base64 32`) at the prompt. **Save the plaintext passphrase in your
password manager *now*, separate from the VPS** — losing it loses the backups by design (the whole
point of client-side encryption). Skip the salt or set one; either is fine, just keep it with the
passphrase.

**4. Set `no_check_bucket = true` on `r2-base`.** rclone's S3 backend defaults to checking the
bucket exists (and creating it if not) before each write. An Object R&W token can't run that
pre-check — it lacks bucket-management permission — so writes fail with 403 regardless of rclone
version unless you flip this flag. Cloudflare's own R2 + rclone documentation calls this out for
object-scoped tokens.

```bash
sed -i '/^\[r2-base\]$/a no_check_bucket = true' ~/.config/rclone/rclone.conf
```

Verify it landed (the awk masks the access key + secret so the output is safe to glance at):

```bash
awk '/^\[/{p=0} /^\[r2-base\]/{p=1} p && !/access_key_id|secret_access_key/' \
  ~/.config/rclone/rclone.conf
```

You should see `no_check_bucket = true` directly under `[r2-base]`, and `[r2-crypt]` should NOT
appear in the output — that confirms the line landed in the correct section.

**5. Lock the rclone config.** It holds the obscured-but-recoverable crypt passphrase, plus the R2
secret key:

```bash
chmod 600 ~/.config/rclone/rclone.conf
```

**6. Smoke-test before wiring cron.**

```bash
BACKUP_REMOTE=r2-crypt: bash ~/doppel/scripts/backup_db.sh
rclone ls r2-crypt:                      # the just-uploaded doppel-*.dump, decrypted view
```

The remote stores opaque mangled blobs; `rclone ls r2-crypt:` shows the original filenames. Expect
the upload to finish in seconds early on — these dumps are small.

**7. Tell cron about `BACKUP_REMOTE`.** Crontab doesn't inherit interactive-shell env, so set it
inside the crontab itself (env lines at the top apply to every entry below):

```bash
( echo "BACKUP_REMOTE=r2-crypt:"; \
  echo "OFFSITE_KEEP_DAYS=30"; \
  crontab -l 2>/dev/null ) | crontab -
```

(Or paste those two lines via `crontab -e`.) On the next nightly run the script dumps locally,
prunes local copies past `KEEP=7`, uploads the new dump to `r2-crypt:`, and deletes remote dumps
older than `OFFSITE_KEEP_DAYS=30` (filtered to the `doppel-*.dump` naming pattern, so a
misconfigured remote can't delete anything outside the backup set). An upload failure leaves the
local dump intact and the script exits non-zero — `tail -F ~/doppel-backups/backup.log` to spot it,
or wire up the healthcheck notifier (§9.2 below) for active alerts instead of passive tailing.

**Restoring from off-box:** on a fresh box, install rclone, recreate the two remotes with the same
endpoint + access keys + crypt passphrase, then `rclone copy
r2-crypt:doppel-YYYYMMDD-HHMMSS.dump .` to fetch the archive, and follow the §10 Restore steps.

### 9.2 Backup failure notifications via healthchecks.io

The local cron + off-box mirror are durable, but their failure modes are *silent* — a stuck docker
daemon, a credentialed-out R2 token, a missed cron tick — they sit in `~/doppel-backups/backup.log`
until tailed. `scripts/backup_db.sh` flips this to a passive **dead-man's switch** when
`BACKUP_HEALTHCHECK_URL` is set: it pings `<URL>/start` after pre-flight, the bare `<URL>` on
success (after off-box mirror, if any), and `<URL>/fail` on any non-zero exit via an EXIT trap.
The service emails when a success ping doesn't arrive by the configured grace time — catching
both code-level failures (the script pinged `/fail`) **and** total no-shows (cron didn't run, box
is off, nothing pinged). Default-off and opt-in, like `BACKUP_REMOTE`.

The script is provider-neutral — any service that accepts `/start` + bare-URL + `/fail` URL
shapes (cronitor.io, a self-hosted check, etc.) works — but the worked example is
**healthchecks.io** (free tier, no card; 20 checks + 100 email alerts/month, plenty for one
nightly backup).

**1. Create the check.** Sign up at healthchecks.io, then add a new check named e.g.
`doppel-backups`:

- **Schedule**: Simple, period 1 day.
- **Grace time**: 2 hours (cron runs at 03:30; allow the dump + off-box upload to land before
  alerting on slowness).
- Copy the **ping URL** at the top of the check page — looks like `https://hc-ping.com/<uuid>`.
  This URL is the credential — anyone with it can spoof success pings and silence real alerts.

**2. Wire the URL into cron.** Add it to the crontab's top-of-file env (like `BACKUP_REMOTE`):

```bash
( echo "BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid>"; \
  crontab -l 2>/dev/null ) | crontab -
```

(Or paste via `crontab -e`.) From the next nightly run on, the script pings `/start` before
`pg_dump`, the bare URL on success at the very end (after the off-box mirror if `BACKUP_REMOTE`
is set), and `/fail` on any non-zero exit. A failed ping (notifier outage, network blip) doesn't
fail the backup — `backup.log` records "healthcheck … ping failed (non-fatal)" and the script
continues; healthchecks.io still alerts via the grace timer if no success ping ever arrives.

**3. Smoke-test before relying on it.**

```bash
BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid> bash ~/doppel/scripts/backup_db.sh
```

The healthchecks.io check page should flip green within seconds. To exercise the failure path
without breaking the real backup, ping `/fail` by hand: `curl -fsS
"https://hc-ping.com/<your-uuid>/fail"` — the dashboard goes red and the alert email arrives.

**On the URL as credential.** The ping URL is unauthenticated; leaking it lets anyone spoof
success pings (and thereby silence real alerts). The script never echoes the URL to logs — only
the ping type — so `~/doppel-backups/backup.log` is safe to share. Keep the URL in the VPS
crontab only (mode 600 by default), never in the repo, never in the rclone config, never in chat
paste.

## 10. Operate

```bash
# Status / logs
dc ps
dc logs -f app
dc logs -f worker

# Restart a service
dc restart app

# Update / redeploy (forward-only migrations)
cd ~/doppel && git pull
dc --profile app build
dc run --rm migrate
dc --profile app up -d            # recreates only changed services

# Restore a backup (DESTRUCTIVE — replaces current data). Custom-format archives need a seekable
# file, so copy the dump into the container rather than piping it. Stop writers first.
dc stop app worker
dc cp ~/doppel-backups/doppel-YYYYMMDD-HHMMSS.dump postgres:/tmp/restore.dump
dc exec postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/restore.dump'
dc --profile app up -d
```

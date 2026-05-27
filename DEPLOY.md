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
cron can't find `docker`, prepend `PATH=/usr/local/bin:/usr/bin:/bin` to the crontab. **Copy archives
off-box** (e.g. `scp`/`rclone` to object storage) for real disaster recovery — a backup that only
lives on the VPS dies with the VPS.

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

# XCTimer — Deploy Runbook (Phase 7)

Built and verified LAN-first on `10.0.1.167:5006`. This is the cutover to Hetzner
prod at `xctimer.com`. Steps marked **[NEEDS ROB]** are outward-facing / irreversible
and must be done (or explicitly approved) by Rob — a Claude session should not do them
unprompted.

## 0. Preconditions
- Code green on LAN (`git log` shows Phases 0–6; `curl localhost:5006/healthz` ok).
- Secrets known: `ANTHROPIC_API_KEY`, `RESEND_API_KEY` (already in `~/track/env` on both boxes).

## 1. GitHub repo  **[NEEDS ROB]**
- Create **private** repo `rdrohde1973/xctimer`.
- New deploy key (don't reuse XC-Timer/Track-Timer keys):
  ```
  ssh-keygen -t ed25519 -f ~/.ssh/github_xctimer_platform -N ""
  # add ~/.ssh/github_xctimer_platform.pub as a deploy key (write access) on the repo
  ```
- `~/.ssh/config` on both boxes:
  ```
  Host github-xctimer-platform
    HostName github.com
    IdentityFile ~/.ssh/github_xctimer_platform
  ```
- Push from the LAN box:
  ```
  cd ~/xctimer
  git remote add origin git@github-xctimer-platform:rdrohde1973/xctimer.git
  git push -u origin main
  ```

## 2. Hetzner app  (5.78.183.9, relay through LAN — see SSH-burst gotcha, handoff §7)
```
ssh rob@10.0.1.167 'ssh rob@5.78.183.9 "
  cd ~ && git clone git@github-xctimer-platform:rdrohde1973/xctimer.git xctimer &&
  cd xctimer && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"'
```
- Create `~/xctimer/env` on Hetzner (copy `ANTHROPIC_API_KEY`/`RESEND_API_KEY`/
  `XC_CLAUDE_MODEL` from `~/xc-district/env`), plus:
  ```
  XC_MAIL_FROM=xctimer@rohde.cc      # rohde.cc is the VERIFIED Resend domain.
  XC_MAIL_FROM_NAME=XCTimer          # xctimer.com is NOT verified in Resend (403);
  XC_HOST=127.0.0.1                  # verify it there later to send as @xctimer.com.
  XC_PORT=5006
  XC_PUBLIC_URL=https://xctimer.com
  XCTIMER_SECRET=<fresh random>
  ```
- Install the service (systemd `--user`, note `.venv` not `venv` on Hetzner — edit
  `ExecStart` to `%h/xctimer/.venv/bin/python -m xctimer.app`):
  ```
  cp ~/xctimer/scripts/xctimer.service ~/.config/systemd/user/
  # edit ExecStart venv path -> .venv
  systemctl --user daemon-reload && systemctl --user enable --now xctimer.service
  ```
- Bootstrap the real super admin (sends a real setup email via Resend)  **[NEEDS ROB]**:
  ```
  cd ~ && ~/xctimer/.venv/bin/python -m xctimer.bootstrap rdrohde@gmail.com "Rob Rohde"
  ```

## 3. Cloudflare tunnel  **[NEEDS ROB]**
- In the Cloudflare Zero Trust dashboard (tunnel `hetzner-prod`), add public hostnames:
  - `xctimer.com` → `http://localhost:5006`
  - `www.xctimer.com` → `http://localhost:5006`
- Leave `alpinexc`/`alpinetrack` pointing at the old apps until cutover.
- Asset cache gotcha (handoff §7 #3): the logo is served from `/static/branding/`.
  If a re-uploaded asset "won't update", version its URL (`?v=<mtime>`) — the landing
  logo is static so this is only relevant once per-district logo uploads land.

## 4. Nightly NAS backups (handoff §6.5 — no LAN/NAS changes needed)
- `scripts/backup.sh` writes `~/backups/xctimer/xctimer-<stamp>.tar.gz` (14-day rotation).
- Ride the existing 02:30 job — add one line to `~/321draw/scripts/backup-all.sh`:
  ```
  BACKUP_DEST="$BACKUP_ROOT/xctimer" "$HOME/xctimer/scripts/backup.sh"
  ```
- The existing `hetzner-backup-pull` job lands it on the NAS automatically. Verify next day:
  ```
  find /mnt/321draw-nas/hetzner/xctimer -name '*.tar.gz'
  ```
- **Test a restore once** with `scripts/restore.sh <archive>` on a throwaway dir.

## 5. Smoke test
```
curl -s https://xctimer.com/healthz          # {"status":"ok",...}
```
Log in, seed the demo district (Districts → Seed demo district), open a meet, check results.

## 6. Ongoing deploys (one relayed SSH connection)
```
ssh rob@10.0.1.167 'ssh rob@5.78.183.9 "cd ~/xctimer && git pull && \
  .venv/bin/python -m py_compile *.py && systemctl --user restart xctimer.service"'
```

## 7. Cutover (later)
- Onboard Alpine as district #1 on the new platform (fresh data, decision #3).
- Once at parity, retire `alpinexc`/`alpinetrack` and repoint if desired.

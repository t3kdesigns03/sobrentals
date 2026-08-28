# Owner Studio — Setup & Runbook

Self-service tool so **Sheila** can submit a new unit (form + drag-drop photos)
and **Brandon** approves it from one email. Nothing goes live until Brandon
clicks **Approve**. $0 to run, no card on file, photos stored in this git repo
(no R2/Cloudinary).

```
Sheila  ->  sobrentals.com/owner/  (passcode gate)
        ->  Cloudflare Worker "sob-owner-studio"  (holds the only GitHub token)
              creates a DRAFT branch (photos + manifest) — nothing on main
              fires repository_dispatch -> GitHub Action emails Brandon
Brandon ->  Approve link -> Worker -> repository_dispatch
              -> GitHub Action resizes photos, clones the nearest sibling page,
                 inserts one card, commits main -> Pages deploys -> LIVE
        ->  Reject link -> Worker deletes the draft branch. Done.
```

Isolation: the Worker uses its default `*.workers.dev` URL (no custom route),
so it can never collide with the `spydernetwork.com` Workers
(`spyder-hls-proxy`, `hls-proxxy`). Don't add a route that shares their zone.

---

## Secrets & config

### A. Cloudflare Worker (set with `wrangler secret put …`, never committed)
| Name | What it is |
|---|---|
| `GITHUB_TOKEN` | Fine-grained PAT for **t3kdesigns03/sobrentals** — Contents: Read/Write (and, if a dispatch 403s, Actions: Read/Write). Nothing else. |
| `OWNER_HASH` | SHA-256 of `SALT + passcode`. The value is in the note Claude sent you. |
| `SIGNING_SECRET` | Random string used to sign session + approve/reject links. Generate any long random value. |

### B. Worker config (already in `owner-studio/worker/wrangler.toml [vars]`, safe to commit)
`GH_OWNER`, `GH_REPO`, `GH_BRANCH`, `OWNER_SALT`, `ALLOWED_ORIGINS`, `SITE_BASE`.

### C. GitHub repo secrets (Settings → Secrets and variables → Actions)
| Name | Value |
|---|---|
| `GMAIL_USERNAME` | the Gmail address that sends the email (e.g. `b.reilly03@gmail.com`) |
| `GMAIL_APP_PASSWORD` | a Google **App Password** (needs 2-Step Verification on) — myaccount.google.com → Security → App passwords |
| `MAIL_TO` | who gets the approval email (e.g. `b.reilly03@gmail.com`) |

The GitHub Actions commit to `main` using the built-in `GITHUB_TOKEN` — no extra
token needed for publishing.

---

## Deploy (one time, ~15 min)

1. **GitHub token** → github.com → Settings → Developer settings → Fine-grained
   tokens → *Generate*. Repository access: **only** `t3kdesigns03/sobrentals`.
   Permissions: **Contents → Read and write** (Metadata read is automatic).
   Copy the token.

2. **Deploy the Worker**
   ```bash
   npm i -g wrangler            # if not installed
   cd owner-studio/worker
   wrangler login
   wrangler secret put GITHUB_TOKEN      # paste the PAT
   wrangler secret put OWNER_HASH        # paste the hash from Claude's note
   wrangler secret put SIGNING_SECRET    # paste any long random string
   wrangler deploy
   ```
   Note the URL it prints, e.g. `https://sob-owner-studio.<your-subdomain>.workers.dev`.

3. **Point the page at the Worker**: open `owner/index.html`, set
   `WORKER_BASE` (near the top of the `<script>`) to that URL, and commit.
   *(For a quick test before committing you can instead visit
   `sobrentals.com/owner/?worker=https://sob-owner-studio.<sub>.workers.dev` —
   it's remembered in that browser.)*

4. **GitHub Actions secrets**: add `GMAIL_USERNAME`, `GMAIL_APP_PASSWORD`,
   `MAIL_TO` (section C above).

5. **Repo must be public** for the email's photo thumbnails and the "Open full
   preview" link to load (they use raw.githubusercontent + htmlpreview). It is
   already public if the Pages site serves from it. If you ever make it private,
   the approval email still works — the thumbnails just won't render.

6. **Old admin host** → copy `owner-studio/redirect-old-host/index.html` over the
   `index.html` in the **SOBmanagement** repo so
   `t3kdesigns03.github.io/SOBmanagement/` bounces owners to
   `sobrentals.com/owner/`.

7. **Give Sheila the passcode** (in Claude's note). To change it later:
   ```bash
   python3 owner-studio/tools/hash_passcode.py "new passphrase"
   # update OWNER_SALT in wrangler.toml, then:
   cd owner-studio/worker && wrangler secret put OWNER_HASH
   wrangler deploy
   ```

> **Do NOT put Cloudflare Access in front of the Worker.** The Approve/Reject
> links are signed GET URLs Brandon clicks from email; an Access login wall would
> block them. The passcode gate + signed tokens are the security model.

---

## Test it end-to-end
- Log in at `/owner/`, pick a community, add a few photos, Submit.
- You get the email → click **Approve** → the Publish Action runs (Actions tab) →
  the unit appears at `sobrentals.com/Properties/<Community>/<page>.html` after
  Pages redeploys (~1–2 min). **Reject** discards it.
- Any unit whose name contains **TEST** publishes the files but is **never**
  added as a public card.

### Verify the transform locally (no secrets, no network)
```bash
python3 owner-studio/publish/publish.py --repo . \
  --manifest _owner_drafts/<draftId>/manifest.json --dry-run
```
This is the exact code the Publish Action runs; `--dry-run` prints what it would
write without touching files.

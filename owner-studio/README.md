# Owner Studio

Private self-service tool for SOB Rentals owners to add a new unit without
sending Brandon a zip of photos. Submit → Brandon gets one approval email →
Approve publishes it to the live site. Nothing goes live without approval.

See **SETUP.md** for deploy steps and the secrets list.

## File map
```
owner/index.html                     the tool (gate + form + uploader) -> sobrentals.com/owner/
owner-studio/
  worker/worker.js                   Cloudflare Worker (login, scrape, draft, approve/reject)
  worker/wrangler.toml               Worker config (name-scoped: sob-owner-studio)
  publish/publish.py                 the publish transform (also runs in the Action)
  tools/hash_passcode.py             rotate the owner passcode
  redirect-old-host/index.html       drop into the old SOBmanagement github.io repo
  SETUP.md                           runbook + secrets
.github/workflows/
  owner-notify.yml                   emails Brandon on a new draft (Gmail SMTP)
  owner-publish.yml                  resizes/compresses, builds page + card, commits main
robots.txt                           blocks /owner/ and /_owner_drafts/ from crawlers
```

## Design guarantees
- **No GitHub token in the browser.** The Worker holds the only credential.
- **Pending is real.** A submission is a git branch (`owner-drafts/<id>`); Pages
  only builds `main`, so a draft is never live. Approve merges the work into
  `main`; Reject deletes the branch.
- **Signed, expiring approvals.** Approve/Reject links are HMAC-signed with ~7-day
  expiry.
- **Matches the site.** The new detail page is cloned from the *nearest sibling*
  in that community (same structure/CSS), and the card matches that community's
  format. Photo folder + filename conventions (`001.jpeg` vs `img001.jpeg`,
  `Unit` prefixes) are auto-detected per community.
- **Image hygiene.** Photos are downscaled in the browser for upload, then the
  Action resizes to ≤2000px JPEG and rejects any >10MB original that won't
  compress under 10MB. No zips in the repo.
- **TEST safety.** A unit name containing `TEST` never gets a public card.
- **Isolated.** Worker uses its `*.workers.dev` URL — zero overlap with the
  spydernetwork.com Workers.

## Best-effort listing import
Pasting a VRBO/Airbnb URL tries to pull title/beds/baths/sleeps/description/
amenities. If the listing blocks it, the fields stay manual and the URL is kept
with the submission — the submit never fails because of a blocked fetch.

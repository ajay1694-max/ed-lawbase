# Hosting ED LawBase on Render — runbook

This deploys the search app to a URL, with a login page and an admin panel for adding officer accounts. Officers get a link and a username/password — nothing to download or install.

**Not Netlify.** Netlify only serves static files; it cannot run the search engine (a Python process reading an 863 MB database on every request). Render runs a real, always-on Python process, which is what this needs.

**Cost.** The smallest plan that keeps the app always on and gives it a disk to hold the database is Render's **Starter** web service (~US$7/month) plus a small disk (~US$0.25/GB/month; 2 GB is enough). There is no free tier that fits — Render's free web services sleep after inactivity and have no persistent disk, so the database would have to re-download on every wake-up.

## One-time setup (you do this, about 15 minutes)

1. **Push this repository to GitHub**, if not already done (a separate step — see the project README). It must include a Release with the `lawbase-data-*.zip` and `SHA256SUMS.txt` assets, and `app/config.json` must have `"repo": "yourorg/ed-lawbase"` set to that repository.
2. **Create a Render account** at render.com (Ajay does this — sign-up and billing are yours to set up).
3. In the Render dashboard: **New → Blueprint**, connect your GitHub account, and pick the `ed-lawbase` repository. Render reads `render.yaml` in this repo and proposes the service and its disk automatically.
4. Before the first deploy, open the service's **Environment** tab and set two secrets:
   - `LAWBASE_ADMIN_PASSWORD` — the password for your own "admin" account. Pick a strong one; you'll use it to sign in the first time.
   - `LAWBASE_SECRET` — any long random string (e.g. 40 random characters). This signs login sessions. **Do not skip this** — without it, a redeploy invalidates every officer's session and, on a host with no disk, every account.
5. Click **Deploy**. First boot downloads the ~230 MB data zip from your GitHub Release onto the disk — watch the logs; this takes a minute or two.
6. Render gives you a URL like `https://ed-lawbase.onrender.com`. Open it — you'll land on the sign-in page.

## Day-to-day

- **Sign in** with `admin` and the password you set.
- **Add an officer:** the navy bar has an **Admin** link (visible to admins only). Add a username and a temporary password, share it with the officer, and ask them to note it down — there's no self-service password change yet, so they come back to you if they forget it.
- **Remove an officer:** same Admin page, "Remove" next to their name.
- **Reset a password:** same page, the "Reset a password" box.
- Officers just open the URL, sign in, and search. Nothing on their end needs installing or updating.

## Updating the case-law data

When you rebuild the database (`pipeline/build.py`) and publish a new GitHub Release, redeploy the Render service (or use Render's "Manual Deploy" button) — `app/update.py` is not wired to auto-poll for updates in hosted mode yet; a redeploy re-runs the startup check and, if you also delete the old file from the disk first (via Render's shell), fetches the new one. Simplest for now: after publishing a new release, use Render's dashboard shell to run `rm data/lawbase.sqlite` then restart the service — it re-downloads automatically on the next boot.

## What stays off this URL

The internal pack (`ed-lawbase-internal`) is never deployed here. This Render service only ever sees the public repository's data — the same CC BY 4.0 judgments and statutes, plus whatever public headnotes and briefs are in `enrich/`.

## If you outgrow this

If usage grows past a handful of officers, or you want the internal pack served too (with its own separate login and stricter access), that's a bigger step — a private deployment inside NIC/ED infrastructure rather than a third-party host. Flag it and we'll plan that separately; it should not be improvised on top of this Render setup.

# AGENTS.md — LIFC Compliance OS (handoff for Codex)

This file briefs a coding agent on the project. It summarises the original build conversation (with Claude, Nov 2026), so you can continue without it.

## Owner and context
- **Owner:** Jaideep Singh, Laxmi India Finance Ltd. (LIFC), Jaipur. LIFC is an RBI-regulated NBFC in the **Middle Layer** under Scale Based Regulation. Jaideep is acting as CCO for this project.
- **Purpose:** a risk-based, weightage-driven tool for testing compliance with RBI Master Directions, in a form that can be shown to RBI inspectors.
- **Delivery preference:** when sending complete files in chat, Jaideep prefers copy-pasteable bash heredocs (`cat > file << 'EOF' … EOF`). He likes step-by-step, hands-on guidance.

## Repository layout
```
server/app.py              FastAPI + SQLite backend (single file, ~1000 lines)
server/static/index.html   The whole web client (HTML + CSS + JS in one file, ~265 KB incl. embedded logo)
server/static/*            PWA manifest, service worker, icons
android/                   Android WebView client (Java, no AndroidX), Gradle/AGP 8.5.2, minSdk 26, targetSdk 34
.github/workflows/build-apk.yml   Builds the APK on GitHub with official Android tooling
deploy/                    systemd unit, nginx HTTPS config, nightly backup script
README.md                  Install, deployment, roles, Android build steps
```

## How to run
```bash
cd server && python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
CCT_DATA=./data uvicorn app:app --host 0.0.0.0 --port 8080
```
The first visit creates the Admin account. The Admin then creates CCO, Reviewer, Tester and Viewer users, each with a temporary password.

## Architecture (key decisions — keep these)
1. **The server is authoritative.** The web app keeps the whole data set (`S`) in memory. `save()` diffs it against the last server copy (`SYNC`) and POSTs path operations to `/api/ops`. The server checks every operation against the user's role, applies it, writes the audit trail, and returns the full state. The client polls `/api/state?rev=` every 30 s.
   - Operation paths: `['settings',k]`, `['settings',map,k]`, `['mdRef',k,f]`, `['library',code(,f)]`, `['rbiObs',id(,f)]`, `['cycles',id(,f)]`, `['cycles',id,'results',code(,f)]`.
   - The client never sends server-owned fields: cycle `status/version/snap/hash/finalisedOn/finalisedBy/submittedOn/submittedBy/log`, or result `att/revBy/revOn`.
2. **Roles** (enforced in `apply_op`, ranks Viewer 0 / Tester 1 / Reviewer 2 / CCO 3; Admin −1):
   - Admin manages users only and is read-only on compliance data.
   - Settings, library, weightage and the reference register are CCO-only.
   - Reviews (`revStat`) need Reviewer or above.
   - **Maker-checker:** a reviewer can't review a result they tested; the server compares the tester's name/username with the reviewer's.
   - **Proof rule:** a Compliant / with-observation / Partially compliant / Non-compliant result can't be agreed without an active attachment, when `settings.requireProof` is on.
   - Editing a sensitive field, or adding or removing evidence, resets an agreed review.
3. **Workflow:** `/api/workflow` handles `submit | return | precheck | finalise | unlock | verify`.
   - Finalise snapshots the weightage into `cycle.snap`, locks the cycle, and stores a SHA-256 of `hash_payload(cycle)` (`sort_keys`, compact JSON).
   - Verify re-hashes the record and every evidence file.
   - Unlock is CCO-only, needs a reason, and bumps the version.
   - Finalised cycles can't be edited or deleted.
4. **Evidence:** `POST /api/attach` (multipart: cycleId, code, file). Files are stored as `data/attachments/<uuid>`, with SHA-256 and metadata in the `attachments` table and in `results[code].att`.
   - Limits: 25 MB, extension allow-list.
   - Delete is a soft delete with a reason; the file is kept.
   - Downloads are served with a sandbox CSP.
5. **Security:**
   - Passwords use PBKDF2-SHA256 (310k iterations) with a policy of 10+ characters and 3 of 4 character classes.
   - Accounts lock for 15 minutes after 5 failures.
   - Sessions end after 30 minutes idle or 12 hours total, using an HttpOnly, SameSite=Strict cookie.
   - Every state-changing request needs the `X-CCT: 1` header (CSRF guard). CSP and other security headers are set in the middleware.
   - Two logs: `auditlog` (per cycle) and `seclog` (authentication and administration events).
6. **Scoring (client):**
   - Item weight = (Impact × Likelihood, or an override) × the Master Direction multiplier.
   - Status factors: C 1, CO 0.75, PC 0.5, NC 0.
   - Bands: Strong ≥ 90, Satisfactory ≥ 75, Needs Improvement ≥ 60, Weak below that.
   - Any Critical-risk NC caps the rating at Needs Improvement.
   - Finalised cycles score with `cycle.snap` (see `cfg()`, `withScope()`).
7. **Requirement library:** the pipe-delimited `RAW` string in `index.html`: `CODE|I|L|freq|cond|dept|area|requirement|procedure|evidence`. It holds about 180 requirements under 27 Master Direction groups, mapped to RBI's consolidated Master Directions of 28-Nov-2025 plus supervisory directions (Fraud Risk, IT/Cyber 2026, Supervisory Returns 2026, statutory audit/RBIA, KYC/PMLA). Applicability conditions: `dep a5k dl gold las transfer colend sec ufs io`.
8. **Report:** `buildReportInner()` produces the inspection pack:
   - Cover, document control, executive summary with CCO statement, methodology, results by Master Direction, findings, RBI observations, action plan, requirements not tested, QA, sign-off.
   - Annexures: reference register, requirement-wise results, evidence register, audit trail.
   - Prints with page headers and footers using `@page` margin boxes. Draft and demo watermarks.
9. **UI:** light "glassmorphism" theme in LIFC brand colours (maroon `#5b0d16`, red `#b3122e`, grey), LIFC logo embedded as base64, sidebar navigation, and a stacked-card testing layout under 700 px.
10. **Android:** `MainActivity` is a WebView shell.
    - First-launch server address screen (`assets/setup.html`), offline page.
    - Evidence upload: `ACTION_GET_CONTENT`, or the camera via MediaStore on API 29+.
    - Downloads through DownloadManager with the session cookie.
    - JS bridge `AndroidBridge.{saveFile, printPage, changeServer, setServer, getServer, retry}`; the web client uses it when present.

## Verified so far (in Claude's sandbox)
- `node --check` on the client JS and `py_compile` on the server both pass.
- Playwright end-to-end run with Chrome:
  - Admin setup and user creation; first-login password change.
  - Tester marks results and uploads a PDF and a JPG.
  - Reviewer agrees SBR-01; agreeing SBR-02 is blocked for missing proof.
  - The server rejects a tester's direct API calls to review or to change settings.
  - CCO finalises and verifies; edits after locking are rejected.
  - Report generates with all annexures; lockout works after 5 bad passwords.
- Mobile layout checked at 390 px.
- `MainActivity.java` compiles with javac against hand-written Android API stand-ins. **The full Gradle build has not been run** (no Android SDK in the sandbox) and the app hasn't been run on a device.

## Known gaps / next steps
- [ ] Run the GitHub Actions APK build (or open in Android Studio) and test on a real phone: login, camera evidence, downloads, print to PDF.
- [ ] Put the server on HTTPS (see `deploy/nginx-compliance-os.conf`), then remove cleartext HTTP in `android/app/src/main/res/xml/network_security_config.xml`.
- [ ] Complete the regulatory reference register. Only CON, CRF and UFS circular numbers are pre-filled. Also validate the thresholds marked "verify" in the library: NOF glide path, gold LTV slabs, NBFC-ML prepayment-charge limit, LEI threshold.
- [ ] Review the default applicability toggles (`DEF_CONDS`) for LIFC.
- [ ] Possible later additions: SSO/LDAP or TOTP two-factor login; email reminders for overdue actions; Postgres instead of SQLite for many concurrent users; splitting `index.html` into modules; automated tests (pytest for `apply_op`/auth, Playwright suite).
- Build artefacts from the original session (`head3.html`, `logic3.js`, `patch3.py`) are **not** included. `server/static/index.html` is the source of truth; edit it directly.

## Conventions
- Don't weaken server-side checks to make the UI easier. Any new data field must be added to the `apply_op` permission rules.
- Keep everything working offline on the LAN: no CDNs or external fonts.
- Audit everything: any new state change must write to `auditlog` through `audit()`.

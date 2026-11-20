# LIFC Compliance OS

Login-based RBI compliance testing for NBFC – Middle Layer (Laxmi India Finance Limited).

```
compliance-os/
├── server/            FastAPI + SQLite server and the web app (static/index.html)
├── android/           Android app (WebView client) – open in Android Studio or build with GitHub Actions
├── deploy/            systemd unit, nginx (HTTPS) config, nightly backup script
└── .github/workflows/ build-apk.yml – builds the APK with Google's official Android SDK
```

## What the system does

| Area | How it works |
|---|---|
| Login & roles | Username and password, stored as PBKDF2-SHA256 hashes (310,000 iterations). Roles are Admin, CCO, Reviewer, Tester and Viewer. All permissions are enforced on the server. |
| Account security | Passwords need at least 10 characters with 3 of 4 character types. Temporary passwords must be changed at first sign-in. Accounts lock for 15 minutes after 5 failed attempts. Sessions end after 30 minutes idle or 12 hours in total. Cookies are HttpOnly and SameSite=Strict. The server sends CSP and anti-clickjacking headers. |
| Segregation of duties | The Admin manages users only and has read-only access to compliance data. A tester can't review their own test (maker-checker rule, enforced on the server). Only the CCO can unlock a finalised cycle, and must give a reason. |
| Proof attachments | Each requirement accepts files or phone-camera photos (max 25 MB each). The server records each file's SHA-256 fingerprint. A reviewer can't agree a Compliant / Partially compliant / Non-compliant result until proof is attached (a CCO setting). Removed evidence is kept on the server and the removal is logged. |
| Audit trail | Every change is recorded on the server against the signed-in user, including rejected attempts. A separate security log covers sign-ins, failures, lock-outs, user changes, evidence views, backups and imports. |
| Finalisation | When a cycle is finalised, the server freezes the weightage, locks the results and evidence, and records a SHA-256 hash. **Verify integrity** re-checks the record and every evidence file. Finalised cycles can't be deleted. |
| Report | The inspection pack has an evidence register annexure listing each file's SHA-256 fingerprint, plus quality-assurance figures: items reviewed, maker-checker conflicts and items without proof. |

## Quick start (test on a PC)

```bash
cd server
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
CCT_DATA=./data uvicorn app:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080. On the first visit you create the **administrator**. The administrator then creates the CCO, reviewers and testers, and each of them gets a one-time temporary password.

## Production install (Ubuntu server, HTTPS)

```bash
sudo useradd -r -s /usr/sbin/nologin compliance
sudo mkdir -p /opt/compliance-os /var/lib/compliance-os && sudo chown compliance: /var/lib/compliance-os
sudo cp -r server deploy /opt/compliance-os/
sudo python3 -m venv /opt/compliance-os/venv
sudo /opt/compliance-os/venv/bin/pip install -r /opt/compliance-os/server/requirements.txt
sudo cp deploy/compliance-os.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now compliance-os
sudo cp deploy/nginx-compliance-os.conf /etc/nginx/sites-available/compliance-os   # edit server_name + certificate paths
sudo ln -s /etc/nginx/sites-available/compliance-os /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
```

Or use Docker: `docker build -t compliance-os server && docker run -d -p 8080:8080 -v /var/lib/compliance-os:/data compliance-os`

**Use HTTPS in production.** It protects passwords and evidence in transit, and Android phones need it to install the app from the browser.

**Backups.** `deploy/backup.sh` copies the database and the evidence files every night. In the app, the CCO can also download a JSON backup of data and logs; evidence files are not included in that, so back up the attachments folder separately.

**Settings** (environment variables): `CCT_DATA` (data folder), `CCT_IDLE_MIN` (default 30), `CCT_SESSION_HOURS` (default 12), `CCT_MAX_MB` (default 25).

## Android

**Option A – install from the browser (no build needed).** Open the HTTPS server address in Chrome on the phone, then tap ⋮ → **Install app** (or **Add to Home screen**). Chrome installs it as an app with the LIFC icon and a full-screen window. Camera capture for evidence works.

**Option B – APK (Android project in `android/`).** The app is a WebView client. It asks for the server address on first launch, and supports evidence upload (files, or the camera on Android 10 and later), downloads, and printing or saving the report as PDF.
- *GitHub:* push this folder to a private repository, then go to **Actions → Build Android APK → Run workflow**. Download the APK from the run's artifacts.
- *Android Studio:* open the `android` folder, then **Build → Build App Bundle(s) / APK(s) → Build APK(s)**.
- *Release signing:* create a key once (`keytool -genkeypair -v -keystore lifc-release.jks -alias lifc -keyalg RSA -keysize 3072 -validity 9125`). Keep it safe: you need it for every future update. Then add it as GitHub secrets: `CCT_KEYSTORE_BASE64` (`base64 -w0 lifc-release.jks`), `CCT_KEYSTORE_PASSWORD`, `CCT_KEY_ALIAS`, `CCT_KEY_PASSWORD`.
- *Distribution:* sideload the APK, or push it through your MDM. Turn off cleartext HTTP in `res/xml/network_security_config.xml` once the server is on HTTPS.

## Roles

| Role | Can do |
|---|---|
| Tester | Record results, observations and proof attachments; maintain the RBI observation register; submit the cycle for review |
| Reviewer | Tester rights, plus maker-checker review of others' tests, cycle details, new cycles, demo data and finalisation |
| CCO | Reviewer rights, plus settings, weightage, library, reference register, unlocking, import and the security log |
| Viewer | Read-only access to everything, e.g. internal audit or the RBI inspection team on site |
| Admin | Users, roles, password resets, unlock/disable accounts, security log. Read-only on compliance data |

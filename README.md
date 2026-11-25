# hddq's repo

Central multi-app F-Droid repository published on Cloudflare Pages and automatically built from GitHub Releases.

- **Landing page**: `https://fdroid.hddq.org/`
- **F-Droid repository URL**: `https://fdroid.hddq.org/repo`

## How it works

1. Apps and retention policies are declared in [`apps.yml`](apps.yml).
2. On manual trigger (`workflow_dispatch`) or cross-repo webhook (`repository_dispatch`), GitHub Actions runs inside the reproducible [`flake.nix`](flake.nix) environment.
3. For each enabled app, the tool queries GitHub Releases and selects:
   - Up to `stable_count` (default `3`) newest non-draft stable releases.
   - Up to `beta_count` (default `1`) newest non-draft pre-releases **only if newer (by SemVer) than the latest stable release**.
4. APKs matching `include_apk_patterns` (and excluding `exclude_apk_patterns`, such as `*universal*`) are downloaded, inspected with `aapt2`, and paired with Fastlane metadata (`fastlane/metadata/android`) transformed into F-Droid's layout.
5. `CurrentVersion` and `CurrentVersionCode` are set from the newest stable release's highest `versionCode`, so F-Droid suggests stable updates by default and places newer pre-releases on the `Beta` channel.
6. `fdroid update --create-metadata` builds and signs the F-Droid index. The publish directory (`_worker.js`, `index.html`, `repo-manifest.json`, and `repo/` **without** `.apk` binaries) is deployed to Cloudflare Pages. Requests for `/repo/*.apk` are streamed by `_worker.js` directly from the corresponding GitHub Releases assets as `200 OK` (with `Range`/`HEAD` support) so F-Droid clients never see a redirect while GitHub tracks download stats natively.

## Initial Setup

### 1. Cloudflare Pages

1. Create a Cloudflare Pages project named `fdroid-repo` (production branch `main`) and attach the custom domain `fdroid.hddq.org`.
2. Point a proxied `CNAME` DNS record for `fdroid.hddq.org` to `fdroid-repo.pages.dev`.

### 2. Repository Secrets

Add the following **Repository secrets** under **Settings → Secrets and variables → Actions**:

| Secret | Description |
| --- | --- |
| `FDROID_REPO_KEYSTORE_BASE64` | Base64-encoded JKS keystore (`base64 -w0 fdroid-repo.jks`) |
| `FDROID_REPO_KEY_ALIAS` | Key alias inside the keystore (e.g. `fdroid`) |
| `FDROID_REPO_KEYSTORE_PASSWORD` | Keystore password |
| `FDROID_REPO_KEY_PASSWORD` | Key password |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token with **Cloudflare Pages: Edit** permission |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Account ID |

> **Tip:** You can reuse the exact same F-Droid keystore secrets already used in `hddq/restoid`, or generate a fresh JKS keystore with:
>
> ```bash
> keytool -genkeypair -v \
>   -storetype jks \
>   -keystore fdroid-repo.jks \
>   -alias fdroid \
>   -keyalg RSA -keysize 2048 -validity 10000 \
>   -dname "CN=hddq's repo, O=hddq"
> base64 -w0 fdroid-repo.jks
> ```
>
> (Note `-storetype jks` ensures separate keystore/key passwords work properly with `apksigner`.)

Optional secret:
- `GH_READ_TOKEN`: Only needed if you later add a **private** Android app repository to `apps.yml`.

## Triggering the Workflow

### Manual Trigger & Release Check

Go to **Actions → Deploy F-Droid Repo → Run workflow**:

- **`mode: deploy`** (default): Checks latest releases of all configured apps, builds the F-Droid repository, and deploys to GitHub Pages.
- **`mode: check-only`**: Checks latest releases of configured apps (optionally filtered by `app_filter`) and prints a summary in the workflow logs and Job Summary without modifying GitHub Pages.

### Webhook Trigger from Other App Repositories (`repository_dispatch`)

When another Android repository (such as `hddq/restoid`) finishes publishing a GitHub Release, it can trigger this repository via GitHub's `repository_dispatch` API.

1. Create a fine-grained Personal Access Token scoped **only** to `hddq/fdroid-repo` with **Contents: Read and write** permission (required by GitHub for `repository_dispatch`).
2. Save it in the app repository's Actions secrets as `FDROID_REPO_DISPATCH_TOKEN`.
3. Add this step to the end of the app's release workflow (after `softprops/action-gh-release`):

```yaml
      - name: Trigger central F-Droid repo update
        if: success()
        env:
          GH_TOKEN: ${{ secrets.FDROID_REPO_DISPATCH_TOKEN }}
        run: |
          gh api repos/hddq/fdroid-repo/dispatches \
            -f event_type=app-released \
            -f "client_payload[repo]=${{ github.repository }}" \
            -f "client_payload[tag]=${{ github.ref_name }}"
```

## Adding More Apps & Configuring Retention

Edit [`apps.yml`](apps.yml) and add another entry under `apps:`:

```yaml
apps:
  - repo: "hddq/restoid"
    app_id: "io.github.hddq.restoid"
    metadata:
      Categories:
        - System
      License: GPL-3.0-only
      AuthorName: hddq
      SourceCode: https://github.com/hddq/restoid
      IssueTracker: https://github.com/hddq/restoid/issues
      Translation: https://crowdin.com/project/restoid

  - repo: "hddq/another-app"
    # app_id is optional; if omitted, it is auto-detected from the APK manifest via aapt2
    stable_count: 5
    beta_count: 0
    exclude_apk_patterns:
      - "*universal*"
    metadata:
      Categories:
        - Utility
      License: MIT
      AuthorName: hddq
      SourceCode: https://github.com/hddq/another-app
```

## Local Development (Nix)

All tools (`python3`, `pyyaml`, `requests`, `pytest`, `ruff`, `fdroidserver`, `aapt2`, `jdk21_headless`, `gh`, `jq`) are defined in [`flake.nix`](flake.nix):

```bash
# Enter dev shell
nix develop

# Run tests and linter
pytest -v
ruff check src tests

# Check latest releases of configured apps
python3 -m fdroid_repo.cli check --config apps.yml

# Build repo locally using a keystore
python3 -m fdroid_repo.cli build \
  --config apps.yml \
  --keystore /path/to/keystore.jks \
  --keystore-pass "..." \
  --key-alias "fdroid" \
  --key-pass "..." \
  --output dist
```

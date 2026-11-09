# Cloud Storage Support

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · [Commands](commands.md) · [Configuration](configuration.md) · [Runners](runners.md) · **State storage** · [CI/CD examples](ci-examples.md)

dbt-ci supports storing and retrieving state files from cloud storage (GCS, S3), making it ideal for distributed CI/CD workflows.

> Requires the matching extra: `pip install 'dbt-ci[gcp]'` for `gs://` URIs, `pip install 'dbt-ci[aws]'` for `s3://` URIs.

## GCS/S3 State Storage

Store your dbt reference state in cloud storage for shared access across CI runs:

```bash
# Initialize and download state from GCS
dbt-ci init \
  --dbt-project-dir dbt \
  --state-uri gs://my-bucket/dbt-state/manifest.json \
  --reference-target production \
  --state dbt/.dbtstate

# Run using cached state (no need to specify URI again)
dbt-ci run --dbt-project-dir dbt --mode models
```

### Per-commit copies of the manifest

`finalize` uploads `<artifacts-uri>/manifest.json` and also keeps a copy for the commit it
ran on, at `<artifacts-uri>/<commit>/manifest.json`. When a deploy uploads to the same
place pull requests read their state from, pull requests
[compare against their merge base](commands.md#comparing-against-the-merge-base) using
those copies, with no extra configuration:

```bash
# Deploy job on main: keeps gs://my-bucket/dbt-state/manifest.json and .../<commit>/manifest.json
dbt-ci finalize --artifacts-uri gs://my-bucket/dbt-state/

# Pull request CI: finds the copy for the commit its branch started from
dbt-ci init --state-uri gs://my-bucket/dbt-state/manifest.json --reference-target production
```

Finding the copies needs permission to list the bucket prefix (e.g. `storage.objects.list`,
or `s3:ListBucket`); without it dbt-ci tries each commit in turn. A lifecycle rule can
expire old copies.

**Benefits:**
- 🔄 **Shared State**: Download the same reference state across different CI jobs
- 💾 **Cache-Based**: After init, commands use local cache (no repeated downloads)
- 📦 **No Git Commits**: State files don't need to be committed to version control
- 🚀 **Scalable**: Works seamlessly in containerized and distributed environments
- 🔐 **Secure**: Leverage cloud IAM and bucket policies for access control

**Configuration:**

The tool uses cloud credentials from your environment. Ensure your bucket is accessible:

```bash
# For GCS
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# For AWS S3
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# Or use IAM roles (recommended in CI/CD)
dbt-ci init --state-uri gs://my-bucket/manifest.json
```

**Supported URI Formats:**
- `gs://bucket-name/path/to/manifest.json` (Google Cloud Storage)
- `s3://bucket-name/path/to/manifest.json` (AWS S3)

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

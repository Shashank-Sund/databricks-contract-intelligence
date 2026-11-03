#!/usr/bin/env bash
# Build the backend-less static demo and publish it to S3 + CloudFront.
# Usage: scripts/deploy_static_demo.sh [blocklist-file]
# Env: AWS_PROFILE / AWS_REGION (default us-east-1), STACK_NAME, APP_NAME.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
region="${AWS_REGION:-us-east-1}"
app="${APP_NAME:-contract-intelligence}"
stack="${STACK_NAME:-public-demo-${app}}"
blocklist="${1:-}"
dist="$here/client/dist"

echo "==> Building the demo bundle"
( cd "$here/client" && npm run build:demo )

echo "==> Scanning the bundle"
"$here/scripts/scan_bundle.sh" "$dist" ${blocklist:+"$blocklist"}

echo "==> Deploying stack $stack"
aws cloudformation deploy \
  --region "$region" \
  --stack-name "$stack" \
  --template-file "$here/deploy/aws/static-demo.cfn.yaml" \
  --parameter-overrides "AppName=$app" \
  --tags project=public-demos "app=$app" \
  --no-fail-on-empty-changeset

out() { aws cloudformation describe-stacks --region "$region" --stack-name "$stack" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
bucket="$(out BucketName)"
dist_id="$(out DistributionId)"
url="$(out Url)"

echo "==> Uploading to s3://$bucket"
# Hashed build assets never change, so cache them for a year.
aws s3 sync "$dist/assets" "s3://$bucket/assets" --region "$region" --delete \
  --cache-control 'public,max-age=31536000,immutable'
# Everything else (index.html, favicon, logos) must revalidate.
aws s3 sync "$dist" "s3://$bucket" --region "$region" --delete \
  --exclude 'assets/*' --cache-control 'no-cache'

echo "==> Invalidating /index.html"
aws cloudfront create-invalidation --distribution-id "$dist_id" --paths /index.html \
  --query 'Invalidation.Id' --output text

echo "==> Waiting for the distribution to be Deployed"
aws cloudfront wait distribution-deployed --id "$dist_id"
echo "Live: $url"

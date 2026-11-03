#!/usr/bin/env bash
# Remove the static demo: empty the bucket, then delete the CloudFormation stack.
# Usage: scripts/teardown_static_demo.sh
set -euo pipefail

region="${AWS_REGION:-us-east-1}"
app="${APP_NAME:-contract-intelligence}"
stack="${STACK_NAME:-public-demo-${app}}"

bucket="$(aws cloudformation describe-stacks --region "$region" --stack-name "$stack" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)"

echo "==> Emptying s3://$bucket"
aws s3 rm "s3://$bucket" --recursive --region "$region"

echo "==> Deleting stack $stack (CloudFront deletion can take several minutes)"
aws cloudformation delete-stack --region "$region" --stack-name "$stack"
aws cloudformation wait stack-delete-complete --region "$region" --stack-name "$stack"
echo "Deleted $stack"

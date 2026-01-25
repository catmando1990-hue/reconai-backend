# CloudFront Setup for Secure S3 Export Downloads

This document provides step-by-step AWS Console instructions for setting up CloudFront to serve private S3 exports with signed URLs.

## Prerequisites

- AWS Account with appropriate permissions
- Private S3 bucket: `reconai-prod-private-exports` (us-east-2)
- S3 exports system (Steps 4-6) completed

---

## Step 1: Create CloudFront Key Pair for Signed URLs

CloudFront signed URLs require an RSA key pair. The private key is used by the backend to sign URLs.

### 1.1 Generate RSA Key Pair (Local Machine)

```bash
# Generate private key (2048-bit RSA)
openssl genrsa -out cloudfront-private-key.pem 2048

# Extract public key
openssl rsa -pubout -in cloudfront-private-key.pem -out cloudfront-public-key.pem
```

### 1.2 Upload Public Key to CloudFront

1. Go to **CloudFront Console** → **Key management** → **Public keys**
2. Click **Create public key**
3. Enter:
   - **Name**: `reconai-exports-signing-key`
   - **Key value**: Paste contents of `cloudfront-public-key.pem`
4. Click **Create public key**
5. **Copy the Key ID** (e.g., `K2EXAMPLE123ABC`) — you'll need this for `CLOUDFRONT_KEY_PAIR_ID`

### 1.3 Create Key Group

1. Go to **CloudFront Console** → **Key management** → **Key groups**
2. Click **Create key group**
3. Enter:
   - **Name**: `reconai-exports-key-group`
   - **Public keys**: Select `reconai-exports-signing-key`
4. Click **Create key group**

### 1.4 Store Private Key Securely

The private key must be stored securely and provided to the backend.

**Option A: Environment Variable (Base64 encoded)**
```bash
# Encode private key as base64 (single line)
cat cloudfront-private-key.pem | base64 -w 0 > cloudfront-private-key.b64

# Set as environment variable
export CLOUDFRONT_PRIVATE_KEY=$(cat cloudfront-private-key.b64)
```

**Option B: AWS Secrets Manager (Recommended for Production)**
```bash
aws secretsmanager create-secret \
  --name reconai/cloudfront-private-key \
  --secret-string file://cloudfront-private-key.pem \
  --region us-east-2
```

**IMPORTANT**: Delete the local private key files after storing securely:
```bash
rm cloudfront-private-key.pem cloudfront-public-key.pem cloudfront-private-key.b64
```

---

## Step 2: Create CloudFront Distribution

### 2.1 Create Distribution

1. Go to **CloudFront Console** → **Distributions** → **Create distribution**

### 2.2 Origin Settings

| Setting | Value |
|---------|-------|
| **Origin domain** | `reconai-prod-private-exports.s3.us-east-2.amazonaws.com` |
| **Origin path** | Leave empty |
| **Name** | `reconai-exports-s3-origin` |
| **Origin access** | **Origin access control settings (recommended)** |

### 2.3 Create Origin Access Control (OAC)

1. Click **Create control setting**
2. Enter:
   - **Name**: `reconai-exports-oac`
   - **Signing behavior**: **Sign requests (recommended)**
   - **Origin type**: **S3**
3. Click **Create**

### 2.4 Default Cache Behavior

| Setting | Value |
|---------|-------|
| **Path pattern** | `Default (*)` |
| **Compress objects automatically** | Yes |
| **Viewer protocol policy** | **Redirect HTTP to HTTPS** |
| **Allowed HTTP methods** | **GET, HEAD** |
| **Restrict viewer access** | **Yes** |
| **Trusted authorization type** | **Trusted key groups** |
| **Trusted key groups** | Select `reconai-exports-key-group` |

### 2.5 Cache Key and Origin Requests

| Setting | Value |
|---------|-------|
| **Cache policy** | `CachingOptimized` (or create custom) |
| **Origin request policy** | `CORS-S3Origin` (optional) |

### 2.6 Settings

| Setting | Value |
|---------|-------|
| **Price class** | Use only North America and Europe (cost optimization) |
| **Alternate domain name (CNAME)** | Optional: `exports.reconai.com` |
| **SSL certificate** | Default CloudFront certificate (or custom if using CNAME) |
| **Default root object** | Leave empty |
| **Standard logging** | Optional: Enable for audit |

### 2.7 Create Distribution

1. Click **Create distribution**
2. Wait for deployment (Status: `Deployed`)
3. **Copy the Distribution domain name** (e.g., `d1234example.cloudfront.net`)

---

## Step 3: Update S3 Bucket Policy

After creating the CloudFront distribution, you must update the S3 bucket policy to allow access only from CloudFront OAC.

### 3.1 Copy the Bucket Policy from CloudFront

1. Go to **CloudFront Console** → **Distributions** → Select your distribution
2. Go to **Origins** tab → Select the S3 origin → **Edit**
3. You'll see a banner: "You must update the S3 bucket policy"
4. Click **Copy policy**

### 3.2 Apply Bucket Policy to S3

1. Go to **S3 Console** → `reconai-prod-private-exports` bucket
2. Go to **Permissions** tab → **Bucket policy** → **Edit**
3. **Replace** the existing policy with the copied policy

The policy should look like this (do not copy directly, use the one from CloudFront):

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowCloudFrontServicePrincipalReadOnly",
            "Effect": "Allow",
            "Principal": {
                "Service": "cloudfront.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::reconai-prod-private-exports/*",
            "Condition": {
                "StringEquals": {
                    "AWS:SourceArn": "arn:aws:cloudfront::ACCOUNT_ID:distribution/DISTRIBUTION_ID"
                }
            }
        }
    ]
}
```

### 3.3 Verify No Public Access

1. Go to **S3 Console** → `reconai-prod-private-exports` bucket
2. Go to **Permissions** tab
3. Verify:
   - **Block public access**: All 4 settings should be **ON**
   - **Bucket policy**: Only CloudFront access
   - **Access control list (ACL)**: No public permissions

---

## Step 4: Configure Backend Environment Variables

Add these environment variables to your deployment:

```bash
# CloudFront Distribution URL (without trailing slash)
CLOUDFRONT_DISTRIBUTION_URL=https://d1234example.cloudfront.net

# CloudFront Key Pair ID (from Step 1.2)
CLOUDFRONT_KEY_PAIR_ID=K2EXAMPLE123ABC

# CloudFront Private Key (base64 encoded)
CLOUDFRONT_PRIVATE_KEY=<base64-encoded-private-key>

# OR if using AWS Secrets Manager
CLOUDFRONT_PRIVATE_KEY_SECRET_ARN=arn:aws:secretsmanager:us-east-2:ACCOUNT_ID:secret:reconai/cloudfront-private-key
```

### Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFRONT_DISTRIBUTION_URL` | Yes* | CloudFront distribution URL |
| `CLOUDFRONT_KEY_PAIR_ID` | Yes* | Key pair ID from CloudFront console |
| `CLOUDFRONT_PRIVATE_KEY` | Yes* | Base64-encoded RSA private key |

*Required for CloudFront mode. If not set, falls back to S3 presigned URLs (dev only).

---

## Step 5: Verify Setup

### 5.1 Test CloudFront Signed URL (Backend)

1. Create a test export via the backend
2. Request a download URL
3. Verify the URL starts with `https://d1234example.cloudfront.net/`
4. Verify the URL contains `Policy`, `Signature`, and `Key-Pair-Id` parameters
5. Verify the URL works and expires correctly

### 5.2 Test Direct S3 Access (Should Fail)

```bash
# This should return 403 Forbidden
curl -I https://reconai-prod-private-exports.s3.us-east-2.amazonaws.com/exports/test.txt
```

### 5.3 Test Unsigned CloudFront URL (Should Fail)

```bash
# This should return 403 Forbidden (missing signature)
curl -I https://d1234example.cloudfront.net/exports/test.txt
```

---

## Troubleshooting

### "Access Denied" on CloudFront URL

1. Verify the key pair ID matches the one in CloudFront key groups
2. Verify the private key matches the public key uploaded to CloudFront
3. Check URL expiration hasn't passed
4. Verify the S3 object exists at the specified key

### "Missing Key" Errors in Backend

1. Verify `CLOUDFRONT_PRIVATE_KEY` is properly base64 encoded
2. Verify the key includes `-----BEGIN RSA PRIVATE KEY-----` header
3. Check for newline encoding issues

### S3 Still Accessible Directly

1. Re-apply the bucket policy from CloudFront console
2. Verify "Block public access" settings are all ON
3. Check for any additional bucket policies

---

## Security Checklist

- [ ] S3 bucket has "Block all public access" enabled
- [ ] S3 bucket policy only allows CloudFront OAC
- [ ] No `s3:ListBucket` permission in bucket policy
- [ ] CloudFront distribution requires signed URLs
- [ ] Private key stored securely (not in code repository)
- [ ] Private key never logged or exposed in API responses
- [ ] CloudFront logging enabled for audit trail

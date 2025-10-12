# Email Integration Design

Future feature: Allow users to email photos directly to scan2wall for processing.

## Overview

Enable users to send photos via email (e.g., to `throw@scan2wall.com`) and receive back a link to the simulation video.

**User Experience**:
1. User takes photo on phone
2. Shares via email to `throw@scan2wall.com`
3. Receives confirmation email immediately
4. Gets follow-up email with video link when processing completes (~1-2 minutes)

---

## Architecture Options

### Option A: Email Polling Service (Simple)

```
┌──────────────────────────────────────────────────────┐
│  Email Server (Gmail, Outlook, etc.)                 │
│  throw@scan2wall.com                                 │
└──────────────┬───────────────────────────────────────┘
               │
               │ IMAP/POP3
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Email Poller Service                                │
│  (Python: imapclient, email)                         │
│                                                       │
│  • Polls every 30s                                   │
│  • Extracts attachments                              │
│  • Validates images                                  │
└──────────────┬───────────────────────────────────────┘
               │
               │ HTTP POST /upload
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Existing scan2wall Pipeline                         │
│  (Upload Server → 3D Gen → Isaac Sim)                │
└──────────────┬───────────────────────────────────────┘
               │
               │ Video ready
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Email Notification Service                          │
│  (SMTP: smtplib, email)                              │
│                                                       │
│  • Send confirmation                                 │
│  • Send video link                                   │
│  • Send error notifications                          │
└──────────────────────────────────────────────────────┘
```

**Pros**:
- Simple to implement
- Works with any email provider
- No special infrastructure needed

**Cons**:
- Polling delay (30s-1min)
- Not scalable for high volume
- Requires email credentials

### Option B: Webhook-Based (Production Ready)

```
┌──────────────────────────────────────────────────────┐
│  Email Service with Webhooks                         │
│  (SendGrid, Mailgun, Postmark)                       │
│  throw@scan2wall.com                                 │
└──────────────┬───────────────────────────────────────┘
               │
               │ HTTP POST (webhook)
               │ Immediate delivery
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Email Webhook Handler                               │
│  (FastAPI endpoint: POST /webhook/email)             │
│                                                       │
│  • Parse multipart email                             │
│  • Extract attachments                               │
│  • Validate sender                                   │
│  • Extract metadata (subject, body)                  │
└──────────────┬───────────────────────────────────────┘
               │
               │ Validate & Queue
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Job Queue (Redis/RabbitMQ)                          │
│  • Stores email + attachment                         │
│  • Tracks user email for reply                       │
└──────────────┬───────────────────────────────────────┘
               │
               │ Process job
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Worker Process                                      │
│  • Upload to existing pipeline                       │
│  • Track job_id                                      │
│  • Monitor status                                    │
└──────────────┬───────────────────────────────────────┘
               │
               │ On completion
               │
               ▼
┌──────────────────────────────────────────────────────┐
│  Email Notification                                  │
│  • Host video on CDN or cloud storage                │
│  • Send link via email                               │
│  • Include preview thumbnail                         │
└──────────────────────────────────────────────────────┘
```

**Pros**:
- Real-time processing
- Scalable architecture
- Professional email handling
- Bounce/spam management built-in

**Cons**:
- Requires external service ($$$)
- More complex setup
- Need CDN/storage for videos

---

## Implementation Recommendation

**Phase 1** (MVP): Option A - Email Polling
**Phase 2** (Production): Option B - Webhooks

---

## Phase 1: Email Polling Implementation

### 1. Email Setup

Choose an email provider:
- **Gmail**: Free, easy setup, good for testing
- **Custom domain**: More professional (e.g., throw@scan2wall.com)

Enable IMAP access and generate app-specific password.

### 2. Code Structure

```
src/scan2wall/email_integration/
├── __init__.py
├── email_poller.py       # Main polling loop
├── email_parser.py       # Extract attachments
├── email_sender.py       # Send notifications
└── config.py             # Email configuration
```

### 3. Environment Variables

Add to `.env`:
```bash
# Email Configuration
EMAIL_ADDRESS=throw@scan2wall.com
EMAIL_PASSWORD=app_specific_password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993

EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587

# Video hosting (temporary public links)
VIDEO_BASE_URL=https://scan2wall.com/videos
VIDEO_EXPIRY_HOURS=48
```

### 4. Email Poller Service

**Pseudocode**:
```python
# email_poller.py

import imaplib
import email
from email.message import EmailMessage
import time
import requests

def poll_inbox():
    """Poll inbox for new emails with attachments."""
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    mail.select('INBOX')

    # Search for unread messages
    status, messages = mail.search(None, 'UNSEEN')

    for msg_num in messages[0].split():
        # Fetch email
        status, data = mail.fetch(msg_num, '(RFC822)')
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        # Extract sender
        sender = email.utils.parseaddr(msg['From'])[1]

        # Find image attachments
        for part in msg.walk():
            if part.get_content_maintype() == 'image':
                image_data = part.get_payload(decode=True)
                filename = part.get_filename() or 'photo.jpg'

                # Process image
                try:
                    job_id = upload_to_pipeline(image_data, filename)
                    send_confirmation(sender, job_id)

                    # Store mapping: job_id -> sender email
                    PENDING_JOBS[job_id] = {
                        'email': sender,
                        'timestamp': time.time()
                    }

                except Exception as e:
                    send_error_email(sender, str(e))

        # Mark as read
        mail.store(msg_num, '+FLAGS', '\\Seen')

    mail.close()
    mail.logout()

def upload_to_pipeline(image_data, filename):
    """Upload image to existing scan2wall pipeline."""
    files = {'file': (filename, image_data, 'image/jpeg')}
    resp = requests.post('http://localhost:49100/upload', files=files)
    resp.raise_for_status()
    return resp.json()['job_id']

def check_completed_jobs():
    """Check if any pending jobs completed."""
    for job_id, info in list(PENDING_JOBS.items()):
        resp = requests.get(f'http://localhost:49100/job/{job_id}')
        data = resp.json()

        if data['status'] == 'done':
            video_url = publish_video(data['processed_path'])
            send_video_email(info['email'], video_url)
            del PENDING_JOBS[job_id]

        elif data['status'] == 'error':
            send_error_email(info['email'], data['error'])
            del PENDING_JOBS[job_id]

def main():
    """Main polling loop."""
    while True:
        try:
            poll_inbox()
            check_completed_jobs()
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(30)  # Poll every 30 seconds

if __name__ == '__main__':
    main()
```

### 5. Email Templates

**Confirmation Email**:
```python
def send_confirmation(to_email, job_id):
    subject = "🎬 Processing your simulation..."
    body = f"""
    Hi there!

    We received your photo and started processing it.

    Job ID: {job_id}
    Estimated time: 1-2 minutes

    You'll receive another email with your simulation video shortly.

    - scan2wall team
    """
    send_email(to_email, subject, body)
```

**Video Ready Email**:
```python
def send_video_email(to_email, video_url):
    subject = "🎉 Your simulation is ready!"
    body = f"""
    Your simulation video is ready!

    Watch it here: {video_url}

    This link will expire in 48 hours.

    Want to create another? Just email us a photo!

    - scan2wall team
    """
    send_email(to_email, subject, body)
```

**Error Email**:
```python
def send_error_email(to_email, error):
    subject = "❌ Processing failed"
    body = f"""
    Unfortunately, we couldn't process your photo.

    Error: {error}

    Common issues:
    - Photo is too blurry
    - File is too large (max 10MB)
    - File is not an image

    Please try again with a different photo.

    - scan2wall team
    """
    send_email(to_email, subject, body)
```

### 6. Video Hosting

**Option 1**: Temporary public directory
```python
def publish_video(video_path):
    """Copy video to public directory and return URL."""
    public_dir = '/var/www/scan2wall/videos'
    filename = f"{uuid.uuid4().hex}.mp4"
    dest = os.path.join(public_dir, filename)
    shutil.copy(video_path, dest)

    # Schedule deletion after 48 hours
    schedule_deletion(dest, hours=48)

    return f"https://scan2wall.com/videos/{filename}"
```

**Option 2**: Cloud storage (S3, GCS)
```python
import boto3

def publish_video(video_path):
    """Upload to S3 with presigned URL."""
    s3 = boto3.client('s3')
    key = f"videos/{uuid.uuid4().hex}.mp4"

    # Upload with expiration lifecycle policy
    s3.upload_file(
        video_path,
        'scan2wall-videos',
        key,
        ExtraArgs={'ContentType': 'video/mp4'}
    )

    # Generate presigned URL (expires in 48h)
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': 'scan2wall-videos', 'Key': key},
        ExpiresIn=172800  # 48 hours
    )

    return url
```

### 7. Running the Service

Add systemd service or use supervisor:

```ini
# /etc/systemd/system/scan2wall-email.service

[Unit]
Description=scan2wall Email Poller
After=network.target

[Service]
Type=simple
User=scan2wall
WorkingDirectory=/home/scan2wall/scan2wall
Environment=PATH=/home/scan2wall/scan2wall/.venv/bin
ExecStart=/home/scan2wall/scan2wall/.venv/bin/python src/scan2wall/email_integration/email_poller.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start service:
```bash
sudo systemctl enable scan2wall-email
sudo systemctl start scan2wall-email
sudo systemctl status scan2wall-email
```

---

## Phase 2: Webhook Implementation (Future)

### 1. Choose Email Service

Recommended services:
- **SendGrid**: $20/month, 100k emails
- **Mailgun**: $35/month, 50k emails
- **Postmark**: $10/month, 10k emails

All support inbound email webhooks.

### 2. Configure Inbound Email

**SendGrid Example**:
1. Verify domain: scan2wall.com
2. Add MX records to DNS
3. Configure inbound parse webhook
4. Point to: `https://api.scan2wall.com/webhook/email`

### 3. Webhook Handler

```python
# Add to server.py

@app.post("/webhook/email")
async def handle_inbound_email(request: Request):
    """Handle inbound email from SendGrid."""
    form = await request.form()

    # Extract email metadata
    sender = form.get('from')
    subject = form.get('subject')
    text = form.get('text')

    # Extract attachments
    attachments = []
    for key in form.keys():
        if key.startswith('attachment'):
            file = form[key]
            if file.content_type.startswith('image/'):
                attachments.append(file)

    if not attachments:
        send_error_email(sender, "No image attachments found")
        return JSONResponse({"status": "no_attachments"})

    # Process first image
    image = attachments[0]
    contents = await image.read()

    # Validate image
    try:
        Image.open(io.BytesIO(contents)).verify()
    except:
        send_error_email(sender, "Invalid image file")
        return JSONResponse({"status": "invalid_image"})

    # Save and queue job
    job_id = uuid.uuid4().hex
    image_path = UPLOAD_DIR / f"{job_id}_{image.filename}"
    image_path.write_bytes(contents)

    # Create job with email info
    JOBS[job_id] = {
        "id": job_id,
        "filename": image.filename,
        "path": str(image_path),
        "status": "queued",
        "created_at": time.time(),
        "email": sender,  # Store sender email
        "processed_path": None,
        "error": None,
    }

    # Process in background
    background_tasks.add_task(_run_pipeline_with_email, job_id, str(image_path))

    # Send confirmation
    send_confirmation(sender, job_id)

    return JSONResponse({"status": "queued", "job_id": job_id})

def _run_pipeline_with_email(job_id: str, path: str):
    """Pipeline with email notification on completion."""
    JOBS[job_id]["status"] = "processing"

    try:
        out_path = process_image(job_id, path)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["processed_path"] = out_path

        # Publish video and send email
        video_url = publish_video(out_path)
        send_video_email(JOBS[job_id]["email"], video_url)

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = repr(e)
        send_error_email(JOBS[job_id]["email"], repr(e))
```

### 4. Email Sending (SendGrid)

```python
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

def send_email(to_email, subject, html_body):
    """Send email via SendGrid."""
    message = Mail(
        from_email='noreply@scan2wall.com',
        to_emails=to_email,
        subject=subject,
        html_content=html_body
    )

    sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
    response = sg.send(message)
    return response.status_code == 202
```

### 5. HTML Email Templates

Use inline CSS for better email client support:

```html
<!-- video_ready.html -->
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .button {
            background: #007bff;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 4px;
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎉 Your simulation is ready!</h1>
        <p>We've finished processing your photo. Watch your object get thrown at a wall in glorious physics simulation!</p>

        <a href="{{ video_url }}" class="button">Watch Video</a>

        <p><small>This link expires in 48 hours.</small></p>

        <hr>
        <p>Want another? Just email us a photo at throw@scan2wall.com</p>
    </div>
</body>
</html>
```

---

## Security Considerations

### Email Validation

```python
def is_valid_email(email: str) -> bool:
    """Basic email validation."""
    import re
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def is_allowed_sender(email: str) -> bool:
    """Check against blacklist/whitelist."""
    # During beta: whitelist only
    if BETA_MODE:
        return email in ALLOWED_EMAILS

    # Check blacklist
    domain = email.split('@')[1]
    if domain in BLOCKED_DOMAINS:
        return False

    return True
```

### Rate Limiting

```python
from collections import defaultdict
import time

RATE_LIMITS = defaultdict(list)  # email -> [timestamp, ...]

def check_rate_limit(email: str, max_requests: int = 5, window: int = 3600):
    """Allow max_requests per window (in seconds)."""
    now = time.time()

    # Remove old requests
    RATE_LIMITS[email] = [
        ts for ts in RATE_LIMITS[email]
        if now - ts < window
    ]

    # Check limit
    if len(RATE_LIMITS[email]) >= max_requests:
        return False

    # Record this request
    RATE_LIMITS[email].append(now)
    return True
```

### Spam Prevention

- Use SendGrid's spam filtering
- Implement CAPTCHA for web upload
- Require email verification for new senders
- Monitor for abuse patterns

---

## Cost Estimates

### Option A: Email Polling (Gmail)
- **Email**: Free (Gmail)
- **Storage**: ~$5/month (100GB Digital Ocean Space)
- **Total**: ~$5/month

### Option B: Webhooks (Production)
- **Email Service**: $20-35/month (SendGrid/Mailgun)
- **Storage/CDN**: $10-20/month (S3 + CloudFront)
- **Total**: ~$30-55/month

---

## Metrics to Track

- Emails received per day
- Processing success rate
- Average processing time
- Bounce rate
- User retention (repeat users)
- Storage usage

---

## Future Enhancements

1. **SMS Notifications**: Text video link instead of email
2. **Social Sharing**: Direct share to Instagram/Twitter
3. **Gallery**: Public gallery of best simulations
4. **Custom Settings**: Email subject line controls physics (e.g., "THROW HARDER")
5. **Video Customization**: Different backgrounds, camera angles
6. **Batch Processing**: Multiple photos in one email → compilation video

---

## Testing Plan

### Local Testing

```python
# test_email.py

def test_email_parsing():
    """Test extracting image from email."""
    with open('test_email.eml', 'rb') as f:
        msg = email.message_from_binary_file(f)
        images = extract_images(msg)
        assert len(images) > 0
        assert images[0]['mime_type'].startswith('image/')

def test_confirmation_send():
    """Test sending confirmation email."""
    result = send_confirmation('test@example.com', 'test_job_123')
    assert result is True

def test_rate_limit():
    """Test rate limiting logic."""
    email = 'test@example.com'
    for i in range(5):
        assert check_rate_limit(email) is True
    assert check_rate_limit(email) is False  # 6th request blocked
```

### Integration Testing

1. Send test email to production address
2. Verify confirmation received
3. Wait for processing
4. Verify video email received
5. Check video link works
6. Verify video expires after 48h

---

## Deployment Checklist

- [ ] Set up email service (Gmail app password or SendGrid)
- [ ] Configure DNS (MX records for custom domain)
- [ ] Add environment variables
- [ ] Set up video hosting (local or S3)
- [ ] Deploy email poller/webhook handler
- [ ] Configure systemd service
- [ ] Test end-to-end flow
- [ ] Set up monitoring/alerts
- [ ] Document email address for users
- [ ] Add email feature to README

---

## Related Files

When implementing, create these files:
- `src/scan2wall/email_integration/email_poller.py`
- `src/scan2wall/email_integration/email_parser.py`
- `src/scan2wall/email_integration/email_sender.py`
- `src/scan2wall/email_integration/config.py`
- `templates/email_confirmation.html`
- `templates/email_video_ready.html`
- `templates/email_error.html`

---

## Questions to Resolve

1. **Which email provider?** Gmail (free) vs SendGrid (pro)
2. **Video hosting?** Self-hosted vs S3/GCS
3. **Expiry policy?** 24h, 48h, or 7 days
4. **Rate limits?** How many submissions per user per hour?
5. **Beta access?** Whitelist only or open to all?
6. **Video watermark?** Add scan2wall branding?
7. **Email replies?** Support "try again" by replying?

---

## Reference Implementation

See these projects for inspiration:
- **Cloudinary**: Email-to-image processing
- **DocuSign**: Email-to-document workflow
- **IFTTT**: Email triggers
- **Zapier**: Email automation

---

Start with Phase 1 (polling) for MVP, then upgrade to Phase 2 (webhooks) for production scale.

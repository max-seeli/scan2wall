# scan2wall Deployment Guide

## Security Fixes Implemented ✅

The following security enhancements have been added to make scan2wall safe for public deployment:

### 1. Rate Limiting (slowapi)
- **10 uploads per hour** per IP address
- **60 status checks per minute** per IP address
- Works seamlessly with Cloudflare (uses `X-Forwarded-For` header)
- Prevents DoS attacks and API cost inflation

### 2. File Size Limits
- **20MB maximum file size** for uploads
- User-friendly error message if exceeded
- Prevents disk space exhaustion

### 3. Privacy Protection
- **`/jobs` endpoint removed** - users can not see other users' data
- Each user only sees their own job via `/job/{job_id}`
- No data leakage between users

### 4. Strong Job IDs
- **Full 32-character UUIDs** (2^128 combinations)
- Prevents enumeration attacks
- Effectively impossible to guess other users' job IDs

### 5. Isaac Worker Security
- **Bound to localhost** (127.0.0.1:8090)
- Not exposed to external network
- Prevents unauthorized simulation requests

## Deployment Options

### Option 1: Cloudflare Tunnel (Recommended, Free)

Expose your server on a custom domain via Cloudflare Tunnel.

**Setup (5 minutes):**
```bash
# 1. Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/

# 2. Login (opens browser to authorize)
cloudflared tunnel login

# 3. Create tunnel
cloudflared tunnel create scan2wall

# 4. Route domain (delete any existing CNAME in Cloudflare first!)
cloudflared tunnel route dns scan2wall yourdomain.com

# 5. Create config (replace TUNNEL-ID with actual ID from step 3)
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: TUNNEL-ID
credentials-file: ~/.cloudflared/TUNNEL-ID.json
ingress:
  - hostname: yourdomain.com
    service: http://localhost:49100
  - hostname: www.yourdomain.com
    service: http://localhost:49100
  - service: http_status:404
EOF

# 6. Start tunnel
cloudflared tunnel run scan2wall
```

**Pros:**
- ✅ Free with any Cloudflare account
- ✅ Custom domain with automatic HTTPS
- ✅ No public IP exposure
- ✅ Works behind firewalls

### Option 2: Direct Brev URL (Immediate)

Use Brev URL directly: `https://49100-mcy6jwb4b.brevlab.com`

**Pros:** ✅ No setup
**Cons:** ❌ Exposes Brev instance

## Starting the Application

### 1. Start Isaac Worker (Docker)

The Isaac Worker starts automatically when you run the start script:

```bash
cd /home/shadeform/scan2wall
./scripts/start.sh auto
```

Verify it's running:
```bash
curl http://localhost:8090/
# Should return: {"status": "ready", "queue_size": 0}
```

### 2. Start Upload Server

```bash
cd /home/shadeform/scan2wall
source .venv/bin/activate
python -m scan2wall.server.run
```

The server will start on port 49100.

### 3. Verify Security Features

**Test rate limiting:**
```bash
# Try 11 uploads in quick succession - 11th should fail
for i in {1..11}; do
  curl -X POST http://localhost:49100/upload \
    -F "file=@test.jpg" \
    -w "\n%{http_code}\n"
  sleep 1
done
# First 10 should succeed (201), 11th should fail (429)
```

**Test file size limit:**
```bash
# Create 25MB file (exceeds 20MB limit)
dd if=/dev/zero of=large.jpg bs=1M count=25
curl -X POST http://localhost:49100/upload \
  -F "file=@large.jpg"
# Should return 413 with user-friendly message
```

**Verify /jobs endpoint is gone:**
```bash
curl http://localhost:49100/jobs
# Should return 404
```

## Monitoring

### Check Server Logs
```bash
# Upload server logs
tail -f /home/shadeform/scan2wall/data/logs/upload.log

# Isaac worker logs
tail -f /home/shadeform/scan2wall/data/logs/isaac_worker.log

# Cloudflared tunnel logs
tail -f /home/shadeform/scan2wall/data/logs/cloudflared.log
```

### Check Disk Space
```bash
df -h /home/shadeform/scan2wall/data
```

Jobs are stored in: `/home/shadeform/scan2wall/data/JOBS/{job_id}/`

**Cleanup old jobs:**
```bash
# Find jobs older than 24 hours
find /home/shadeform/scan2wall/data/JOBS -type d -mtime +1
# Delete them
find /home/shadeform/scan2wall/data/JOBS -type d -mtime +1 -exec rm -rf {} +
```

### Monitor API Costs

Check your Google Cloud Console for Gemini API usage:
https://console.cloud.google.com/

Each upload triggers 4 Gemini API calls (~$0.02-0.05).

**Expected costs:**
- 10 users/day: ~$2-5/day
- 100 users/day: ~$20-50/day

## Performance Under Load

### Current Bottlenecks

1. **3D Generation**: Sequential (ComfyUI processes one at a time)
   - User 1: 0s wait
   - User 2: ~60s wait
   - User 10: ~540s wait (9 minutes)

2. **Simulation**: Sequential (Isaac Sim processes one at a time)
   - Adds ~15s per queued user

### Expected Response Times

| Concurrent Users | Wait Time (User N) |
|------------------|--------------------|
| 1                | ~150s (2.5 min)    |
| 2                | ~210s (3.5 min)    |
| 5                | ~390s (6.5 min)    |
| 10               | ~690s (11.5 min)   |

**For LinkedIn demo**: Expect 5-10 concurrent users max. System should handle this fine.

## Troubleshooting

### "Rate limit exceeded"
**Cause**: User hit 10 uploads/hour or 60 status checks/minute
**Fix**: Wait for rate limit window to reset (1 hour for uploads)

### "File too large"
**Cause**: Image exceeds 20MB
**Fix**: Compress image or take photo at lower resolution

### "Job not found"
**Cause**: Invalid job ID or job expired
**Fix**: Check job ID is correct 32-character hex string

### Isaac Worker not responding
```bash
# Check if running
curl http://localhost:8090/
# If not, check Docker
docker ps | grep vscode
# Restart if needed
cd /home/shadeform/scan2wall/isaac/isaac-launchable/isaac-lab
docker compose restart
```

### Upload server crashed
```bash
# Check for port conflicts
lsof -ti:49100
# Kill and restart
lsof -ti:49100 | xargs kill -9
cd /home/shadeform/scan2wall
source .venv/bin/activate
python -m scan2wall.server.run
```

## Security Checklist

Before posting on LinkedIn:

- [x] slowapi rate limiting enabled
- [x] 20MB file size limit enforced
- [x] Full 32-character UUIDs used
- [x] `/jobs` endpoint removed
- [x] Isaac Worker bound to localhost
- [x] Cloudflare Tunnel configured
- [ ] Google API key in `.env` (never commit!)
- [ ] `.env` in `.gitignore`
- [ ] Cloudflared tunnel running (`cloudflared tunnel run scan2wall`)

## Post-Launch Monitoring

### First 24 Hours
- Monitor disk space (jobs accumulate)
- Watch Gemini API costs
- Check error logs for issues

### First Week
- Implement job cleanup (delete > 24 hours)
- Add monitoring alerts (disk, costs)
- Consider adding user feedback form

## Cost Breakdown

| Service | Cost | Notes |
|---------|------|-------|
| Brev GPU | ~$1-2/hour | Pay per use |
| Fly.io Proxy | $0/month | Free tier |
| Gemini API | $0.02-0.05/upload | 4 calls per upload |
| Domain | $12/year | If using custom domain |

**Expected monthly cost for 100 users/day:**
- Brev: Variable (depends on usage hours)
- Gemini: ~$60-150/month
- Fly.io: $0
- **Total: ~$60-150/month** (excluding GPU time)

## Support

- **Fly.io Issues**: https://community.fly.io/
- **Rate Limiting**: https://github.com/laurentS/slowapi
- **Caddy**: https://caddyserver.com/docs/

## Architecture Diagram

```
┌─────────────┐
│   User      │
│  (Browser)  │
└──────┬──────┘
       │ HTTPS
       │
┌──────▼──────────────┐
│ Cloudflare Tunnel   │  (scan2wall.com)
│  + Auto HTTPS       │  (Free)
└──────┬──────────────┘
       │ Encrypted Tunnel
       │
┌──────▼──────────────┐
│  FastAPI Server     │  (Port 49100)
│  + slowapi          │  (Rate Limiting)
│  + File Validation  │  (20MB max)
└──────┬──────────────┘
       │
       ├──────────────────┐
       │                  │
┌──────▼──────┐    ┌─────▼─────────┐
│  Gemini API │    │  ComfyUI      │
│  (Material) │    │  (3D Gen)     │
└─────────────┘    └───────┬───────┘
                           │
                    ┌──────▼────────┐
                    │  Isaac Worker │
                    │  (localhost)  │
                    │  Simulation   │
                    └───────────────┘
```

## Next Steps

1. **Start all services**: `./scripts/start.sh auto`
2. **Start Cloudflare Tunnel**: `cloudflared tunnel run scan2wall`
3. **Test your domain**: Visit `https://yourdomain.com`
4. **Post on LinkedIn** with URL
5. **Monitor costs and performance**

Good luck with your launch! 🚀

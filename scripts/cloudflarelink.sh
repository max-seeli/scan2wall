#!/bin/bash
set -e

# Parse arguments
port=49100
while [[ $# -gt 0 ]]; do
    case $1 in
        --port) port="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== Cloudflare Tunnel Setup ==="
echo "Port: $port"
echo ""

# Load .env if exists
if [ -f ~/scan2wall/.env ]; then
    source ~/scan2wall/.env
fi

# Check cloudflared installed
command -v cloudflared &> /dev/null || { echo "Error: Install cloudflared first (run setup.sh)"; exit 1; }

# Check if running in headless/remote environment
if [ -z "$DISPLAY" ] && [ -z "$SSH_CLIENT" ]; then
    echo "⚠️  Warning: No display detected. Browser may not open automatically."
fi

# 1. Authenticate
echo "Step 1: Authenticate..."

# Check if already authenticated
if [ -f ~/.cloudflared/cert.pem ]; then
    echo "✓ Already authenticated (cert.pem exists)"
else
    echo "  Opening browser for Cloudflare login..."
    echo "  If browser doesn't open, copy the URL and open manually."
    echo ""

    # Run with timeout (5 minutes)
    if timeout 300 cloudflared tunnel login 2>&1; then
        if [ ! -f ~/.cloudflared/cert.pem ]; then
            echo ""
            echo "❌ Authentication failed: Certificate not created"
            exit 1
        fi
        echo "✓ Authentication successful"
    else
        echo ""
        echo "❌ Authentication failed"
        echo ""
        echo "Alternatives:"
        echo "  1. Manual: scp cert.pem from local machine to ~/.cloudflared/"
        echo "  2. Dashboard: https://one.dash.cloudflare.com/ → Networks → Tunnels"
        exit 1
    fi
fi
echo ""

# 2. Create tunnel
tunnel_name="scan2wall"
echo "Using tunnel name: $tunnel_name"
tunnel_id=$(cloudflared tunnel create "$tunnel_name" 2>&1 | grep -oP 'with id \K[a-f0-9-]+' || cloudflared tunnel list | grep "$tunnel_name" | awk '{print $1}')
echo "Tunnel ID: $tunnel_id"

# Auto-recover credentials if missing
credentials_file=~/.cloudflared/$tunnel_id.json
if [ ! -f "$credentials_file" ]; then
    python3 -c "import json, base64; token = json.loads(base64.b64decode('$(cloudflared tunnel token $tunnel_id)')); creds = {'AccountTag': token['a'], 'TunnelSecret': token['s'], 'TunnelID': token['t']}; print(json.dumps(creds, indent=2))" > "$credentials_file"
fi
echo ""

# 3. Route domain
domain_name="scan2wall.com"
echo "Using domain: $domain_name"

echo "Configuring DNS route..."

# Extract base domain (e.g., "example.com" from "sub.example.com")
base_domain=$(echo "$domain_name" | awk -F. '{print $(NF-1)"."$NF}')

# Try to delete existing DNS records via API
echo "Checking for existing DNS records..."

# Check if token is already in .env
if [ -n "$CF_API_TOKEN" ]; then
    echo "Using saved Cloudflare API token..."
    cf_token="$CF_API_TOKEN"
else
    read -p "Do you have a Cloudflare API token to auto-fix DNS? (y/N): " has_token
    if [[ $has_token =~ ^[Yy]$ ]]; then
        read -p "Enter Cloudflare API Token: " cf_token
        # Save token to .env for future use
        if [ -f ~/scan2wall/.env ] && [ -n "$cf_token" ]; then
            sed -i 's|^# CF_API_TOKEN=.*|CF_API_TOKEN='"$cf_token"'|' ~/scan2wall/.env
            echo "✓ Token saved to .env for future use"
        fi
    fi
fi

if [ -n "$cf_token" ]; then
    # Get zone ID
    zone_id=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones?name=$base_domain" \
        -H "Authorization: Bearer $cf_token" \
        -H "Content-Type: application/json" | grep -oP '"id":"\K[^"]+' | head -1)

    if [ -n "$zone_id" ]; then
        echo "Found zone ID: $zone_id"

        # Find and delete existing DNS record
        record_id=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones/$zone_id/dns_records?name=$domain_name" \
            -H "Authorization: Bearer $cf_token" \
            -H "Content-Type: application/json" | grep -oP '"id":"\K[^"]+' | head -1)

        if [ -n "$record_id" ]; then
            echo "Deleting existing DNS record..."
            curl -s -X DELETE "https://api.cloudflare.com/client/v4/zones/$zone_id/dns_records/$record_id" \
                -H "Authorization: Bearer $cf_token" \
                -H "Content-Type: application/json" > /dev/null
            echo "✓ Old DNS record deleted"
            sleep 2
        fi
    fi
fi

# Now add the tunnel route
if cloudflared tunnel route dns "$tunnel_name" "$domain_name" 2>&1; then
    echo "✓ DNS route configured"
else
    echo ""
    echo "⚠️  DNS route failed. Manual fix:"
    echo "  1. Go to: https://dash.cloudflare.com"
    echo "  2. Delete existing DNS record for: $domain_name"
    echo "  3. Run: cloudflared tunnel route dns $tunnel_name $domain_name"
    echo ""
    echo "Continuing anyway (tunnel will run but may not be accessible)..."
fi
echo ""

# 4. Create config
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: $tunnel_id
credentials-file: ~/.cloudflared/$tunnel_id.json
ingress:
  - hostname: $domain_name
    service: http://localhost:$port
  - service: http_status:404
EOF

echo "✓ Configuration complete!"
echo ""

# 5. Start the tunnel
echo "Step 5: Starting tunnel..."
echo ""

# Kill any existing cloudflared processes
pkill -f "cloudflared tunnel run" 2>/dev/null || true
sleep 1

# Start tunnel in background with logs
mkdir -p ~/scan2wall/data/logs
nohup cloudflared tunnel run "$tunnel_id" > ~/scan2wall/data/logs/cloudflared.log 2>&1 &
TUNNEL_PID=$!

# Wait a moment for startup
sleep 3

# Verify it's running
if ps -p $TUNNEL_PID > /dev/null; then
    echo "✓ Tunnel started successfully (PID: $TUNNEL_PID)"
    echo ""
    echo "============================================"
    echo "✓ Cloudflare Tunnel is LIVE!"
    echo "============================================"
    echo ""
    echo "Your site is accessible at:"
    echo "  https://$domain_name (→ localhost:$port)"
    echo ""
    echo "Tunnel logs: ~/scan2wall/data/logs/cloudflared.log"
    echo ""
    echo "To stop the tunnel:"
    echo "  pkill -f 'cloudflared tunnel run'"
    echo ""
    echo "To restart the tunnel:"
    echo "  cloudflared tunnel run $tunnel_id"
else
    echo "⚠️  Tunnel started but may not be running"
    echo "Check logs: tail -f ~/scan2wall/data/logs/cloudflared.log"
    exit 1
fi

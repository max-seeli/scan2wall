#!/bin/bash
set -e

echo "=== Cloudflare Tunnel Setup ==="
echo ""

# Check cloudflared installed
command -v cloudflared &> /dev/null || { echo "Error: Install cloudflared first (run setup.sh)"; exit 1; }

# 1. Authenticate
echo "Step 1: Authenticate (opens browser)..."
cloudflared tunnel login || { echo "Auth failed"; exit 1; }
echo ""

# 2. Create tunnel
read -p "Tunnel name (e.g., scan2wall): " tunnel_name
tunnel_id=$(cloudflared tunnel create "$tunnel_name" 2>&1 | grep -oP 'with id \K[a-f0-9-]+' || cloudflared tunnel list | grep "$tunnel_name" | awk '{print $1}')
echo "Tunnel ID: $tunnel_id"
echo ""

# 3. Route domain
read -p "Domain (e.g., scan2wall.com): " domain_name
cloudflared tunnel route dns "$tunnel_name" "$domain_name"
echo ""

# 4. Create config
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: $tunnel_id
credentials-file: ~/.cloudflared/$tunnel_id.json
ingress:
  - hostname: $domain_name
    service: http://localhost:49100
  - service: http_status:404
EOF

echo "✓ Done! Start with: ./scripts/start.sh auto"
echo "Access at: https://$domain_name"

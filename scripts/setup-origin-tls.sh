#!/bin/bash
# Runs on the Beanstalk host, never inside the application container.
set -euo pipefail
exec 9>/var/lock/archreactor-origin-tls.lock
flock -w 300 9
get_config=/opt/elasticbeanstalk/bin/get-config
origin_host=$("$get_config" environment -k ORIGIN_TLS_HOST 2>/dev/null || true)
public_host=$("$get_config" environment -k PUBLIC_HTTPS_HOST 2>/dev/null || true)
https_only=$("$get_config" environment -k ORIGIN_HTTPS_ONLY 2>/dev/null || true)
[[ -n "$origin_host" ]] || exit 0
[[ "$origin_host" =~ ^[a-zA-Z0-9.-]+\.elasticbeanstalk\.com$ ]] || { echo 'Invalid origin TLS hostname'; exit 1; }
[[ "$public_host" =~ ^[a-zA-Z0-9.-]+\.cloudfront\.net$ ]] || { echo 'Invalid public HTTPS hostname'; exit 1; }
systemctl enable --now amazon-ssm-agent
systemctl restart amazon-ssm-agent

if [[ ! -x /opt/archreactor-certbot/bin/certbot ]]; then
    dnf install -y python3.11
    python3.11 -m venv /opt/archreactor-certbot
    /opt/archreactor-certbot/bin/pip install --disable-pip-version-check 'certbot==5.4.0'
fi
certbot=/opt/archreactor-certbot/bin/certbot
webroot=/var/lib/archreactor-acme
install -d -m 0755 "$webroot/.well-known/acme-challenge"
install -d -m 0700 /etc/letsencrypt
install -d -m 0755 /etc/nginx/conf.d/elasticbeanstalk
cat > /etc/nginx/conf.d/elasticbeanstalk/01_archreactor_acme.conf <<EOF
location ^~ /.well-known/acme-challenge/ {
    root $webroot;
    default_type text/plain;
    try_files \$uri =404;
}
EOF
# HTTP remains available until CloudFront's HTTPS-only cutover is complete.
if [[ "$https_only" == true ]]; then
    cat > /etc/nginx/conf.d/01_archreactor_http_map.conf <<'EOF'
map "$scheme:$uri" $archreactor_redirect_http {
    default 0;
    ~^http:/\.well-known/acme-challenge/ 0;
    "http:/" 0;
    ~^http: 1;
}
EOF
    cat >> /etc/nginx/conf.d/elasticbeanstalk/01_archreactor_acme.conf <<EOF
if (\$archreactor_redirect_http) { return 308 https://$public_host\$request_uri; }
EOF
else
    rm -f /etc/nginx/conf.d/01_archreactor_http_map.conf
fi
nginx -t
systemctl reload nginx

if [[ ! -s /etc/letsencrypt/live/archreactor-origin/fullchain.pem ]]; then
    "$certbot" certonly --dry-run --webroot -w "$webroot" --non-interactive \
        --agree-tos --register-unsafely-without-email --cert-name archreactor-origin -d "$origin_host"
fi
"$certbot" certonly --webroot -w "$webroot" --non-interactive --agree-tos \
    --register-unsafely-without-email --keep-until-expiring --cert-name archreactor-origin -d "$origin_host"

# The Docker platform defines its own upstream, unlike language platform mappings.
nginx -T 2>/dev/null | grep -E 'upstream[[:space:]]+docker[[:space:]]*\{' >/dev/null || { echo 'Missing Beanstalk Docker upstream'; exit 1; }
cat > /etc/nginx/conf.d/02_archreactor_tls.conf <<EOF
server {
    listen 443 ssl;
    server_name $origin_host;
    ssl_certificate /etc/letsencrypt/live/archreactor-origin/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/archreactor-origin/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:archreactor_tls:10m;
    ssl_session_timeout 1d;
    access_log /var/log/nginx/access.log main;
    include /etc/nginx/conf.d/elasticbeanstalk/01_archreactor_acme.conf;
    location / {
        proxy_pass http://docker;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF
nginx -t
systemctl reload nginx

cat > /usr/local/sbin/archreactor-renew-origin-tls <<'EOF'
#!/bin/bash
set -euo pipefail
exec 9>/var/lock/archreactor-origin-tls.lock
flock -w 300 9
/opt/archreactor-certbot/bin/certbot renew --quiet --deploy-hook 'nginx -t && systemctl reload nginx'
EOF
chmod 0750 /usr/local/sbin/archreactor-renew-origin-tls
cat > /etc/systemd/system/archreactor-origin-tls-renew.service <<'EOF'
[Unit]
Description=Renew ArchReactor origin TLS certificate
Wants=network-online.target
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/archreactor-renew-origin-tls
EOF
cat > /etc/systemd/system/archreactor-origin-tls-renew.timer <<'EOF'
[Unit]
Description=Check ArchReactor TLS renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now archreactor-origin-tls-renew.timer
openssl x509 -in /etc/letsencrypt/live/archreactor-origin/fullchain.pem -noout -subject -issuer -dates
printf 'Origin TLS ready; automatic renewal enabled.\n'

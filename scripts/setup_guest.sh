#!/system/bin/sh
# Run on the LDPlayer guest (as root) to redirect the Niantic/PTC hostnames to
# 127.0.0.1 and trust our CA, WITHOUT writing to the read-only /system: we
# bind-mount writable copies over the system files. Persists until reboot.

# --- hosts: redirect endpoints to 127.0.0.1 (reached via 'adb reverse') ---
cp /system/etc/hosts /data/local/tmp/hosts
cat >> /data/local/tmp/hosts <<EOF
127.0.0.1 pgorelease.nianticlabs.com
127.0.0.1 sso.pokemon.com
127.0.0.1 holo.nianticlabs.com
127.0.0.1 www.nianticlabs.com
EOF
mount -o bind /data/local/tmp/hosts /system/etc/hosts

# --- CA: clone the system trust store + add ours, then bind it over ---
rm -rf /data/local/tmp/cacerts
mkdir -p /data/local/tmp/cacerts
cp /system/etc/security/cacerts/* /data/local/tmp/cacerts/ 2>/dev/null
cp /data/local/tmp/pogo-ca.crt /data/local/tmp/cacerts/217161b5.0
chmod 644 /data/local/tmp/cacerts/*
chown root:root /data/local/tmp/cacerts/*
chcon u:object_r:system_file:s0 /data/local/tmp/cacerts/* 2>/dev/null
mount -o bind /data/local/tmp/cacerts /system/etc/security/cacerts

echo "=== hosts ==="
cat /system/etc/hosts
echo "=== our CA in store ==="
ls -l /system/etc/security/cacerts/217161b5.0
echo "=== store count ==="
ls /system/etc/security/cacerts/ | wc -l

#!/system/bin/sh
# Run on the Android 6 AVD (as root, after `adb root && adb remount`) to redirect
# the Niantic/PTC hostnames to the host PC (reachable at 10.0.2.2 from a standard
# emulator) and trust our CA. On API 23 the game needs no plugin-load hook.

# hosts -> host loopback (10.0.2.2 on AOSP emulator)
cat >> /system/etc/hosts <<EOF
10.0.2.2 pgorelease.nianticlabs.com
10.0.2.2 sso.pokemon.com
10.0.2.2 holo.nianticlabs.com
10.0.2.2 www.nianticlabs.com
EOF

# CA into the system trust store (hash filename computed on host = 217161b5.0)
cp /data/local/tmp/pogo-ca.crt /system/etc/security/cacerts/217161b5.0
chmod 644 /system/etc/security/cacerts/217161b5.0
chown root:root /system/etc/security/cacerts/217161b5.0

echo "=== hosts ==="; cat /system/etc/hosts
echo "=== our CA ==="; ls -l /system/etc/security/cacerts/217161b5.0

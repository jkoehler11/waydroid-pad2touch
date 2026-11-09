# Waydroid has no internet (and web pages are blank) when Docker is installed

**Symptom:** Waydroid starts fine, apps launch, but nothing that needs the network works — in‑app
login web views are blank, Chrome says the page can't be loaded, Play Store spins. The mouse and
keyboard work fine, so the container doesn't look broken.

**Cause:** Docker sets the host's IPv4 `FORWARD` policy to `DROP`. Waydroid's network lives in its
own nftables table (`inet lxc`, `ip lxc`) whose forward chain *does* accept `waydroid0` — but an
`accept` in one nftables base chain cannot override a `drop` in another. Every packet from the
container therefore dies at Docker's `FORWARD` chain. DHCP and DNS still work (they are handled
locally by Waydroid's own `dnsmasq` on `192.168.240.1`), which is why the container looks online
until you try to open something.

## Confirm it in 30 seconds

From the host:

```bash
sudo nft list chain ip filter FORWARD      # look for: policy drop
```

Inside the container (get a shell with `waydroid adb connect`, then
`adb -s 192.168.240.112:5555 shell`):

```bash
ping -c2 192.168.240.1      # gateway: works
ping -c2 8.8.8.8            # 100% packet loss  <-- the tell
curl -sS -o /dev/null -w '%{http_code}\n' https://example.com   # times out / fails
```

Note that names still resolve — DNS is fine. Only forwarded traffic is dropped.

## Fix

Insert two accepts at the top of Docker's `DOCKER-USER` chain, which is evaluated before the default
drop and is preserved by Docker across restarts:

```bash
sudo iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT
sudo iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT
```

Check:

```bash
sudo iptables -S DOCKER-USER
# -A DOCKER-USER -i waydroid0 -j ACCEPT
# -A DOCKER-USER -o waydroid0 -j ACCEPT
```

Make it survive reboots with a oneshot unit — `/etc/systemd/system/waydroid-docker-forward.service`:

```ini
[Unit]
Description=Allow Waydroid (waydroid0) traffic past Docker's FORWARD DROP policy
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/bash -c 'iptables -C DOCKER-USER -i waydroid0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT; iptables -C DOCKER-USER -o waydroid0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT'

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now waydroid-docker-forward.service
```

The fix takes effect immediately — no Waydroid restart needed. Verify inside the container:
`ping -c2 8.8.8.8` and `curl -I https://example.com`.

## Things that look like the cause but aren't

- **DNS / Tailscale.** Waydroid's `dnsmasq` forwards to whatever `/etc/resolv.conf` says, and if
  Tailscale owns that file it points at `100.100.100.100`. Test it directly from the host:
  `nslookup example.com 192.168.240.1`. If that answers, DNS is not your problem.
- **WebView / Chrome missing.** Check what Android actually has before installing anything:
  `adb shell dumpsys input`-style introspection works there too, and `dumpsys connectivity` shows
  the network stuck without `VALIDATED` — that's a symptom of the drop, not a missing WebView.
- **`sudo iptables -P FORWARD ACCEPT`** works but Docker resets the policy when it starts; the
  `DOCKER-USER` rules above are the durable form.

## Credit where due: the container is fine

Everything else in Waydroid is unaffected, including pointer/keyboard injection, so the fix is
purely on the host's firewall path.

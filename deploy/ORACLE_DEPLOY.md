# Deploying on Oracle Cloud "Always Free" (handles 20 GB uploads)

This runs the panel on a permanently-free Oracle ARM VM with a large disk for
media. End result: `http://<your-ip>/` serving the WhatsApp-themed panel.

> Free tier note: the Always Free Ampere A1 allocation is 2 OCPU / 12 GB RAM
> (reduced in June 2026) and up to ~200 GB of block storage — plenty for this.

---

## 1. Create the account & VM

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is required for identity
   verification; Always Free resources are not charged).
2. Console → **Compute → Instances → Create instance**.
   - **Image:** Canonical Ubuntu 24.04 (or 22.04).
   - **Shape:** change to **Ampere (Arm) → VM.Standard.A1.Flex**, e.g. 2 OCPU / 12 GB.
     (If you get an "out of capacity" error, try another Availability Domain/region.)
   - **Networking:** keep "Assign a public IPv4 address".
   - **SSH keys:** upload your public key (or let it generate one and download it).
3. Create. Note the **public IP**.

## 2. Open the firewall (two layers — both matter)

**a) Oracle Security List** (cloud firewall)
Console → your VM → **Virtual Cloud Network → Security Lists → Default** → add
**Ingress Rules**:
- Source `0.0.0.0/0`, TCP, dest port **80**
- Source `0.0.0.0/0`, TCP, dest port **443** (if you add HTTPS later)

**b) The VM's own iptables** (Oracle Ubuntu images block ports by default — the classic gotcha):
```bash
sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Attach a data disk for media (recommended)

Uploaded exports are large — keep them off the boot volume.
Console → **Block Storage → Block Volumes → Create** (e.g. 150 GB, within the free
200 GB), then **attach** it to the instance (Paravirtualized). Then on the VM:
```bash
lsblk                                   # find the new disk, e.g. /dev/sdb
sudo mkfs.ext4 /dev/sdb
sudo mkdir -p /mnt/data
sudo mount /dev/sdb /mnt/data
echo '/dev/sdb /mnt/data ext4 defaults,_netdev,nofail 0 2' | sudo tee -a /etc/fstab
sudo mkdir -p /mnt/data/storage && sudo chown ubuntu:ubuntu /mnt/data/storage
```
(If you skip this, the app just uses `storage/` on the boot disk.)

## 4. Install dependencies

```bash
ssh ubuntu@<your-ip>
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

## 5. Get the code & build the venv

```bash
sudo mkdir -p /opt/whatsapp-viewer && sudo chown ubuntu:ubuntu /opt/whatsapp-viewer
git clone https://github.com/sanmol916/whatsapp-export-viewer.git /opt/whatsapp-viewer
cd /opt/whatsapp-viewer/backend
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

## 6. Run it as a service (systemd)

```bash
sudo cp /opt/whatsapp-viewer/deploy/whatsapp-viewer.service /etc/systemd/system/
# The unit already sets WA_STORAGE_DIR=/mnt/data/storage — edit if you skipped step 3.
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-viewer
sudo systemctl status whatsapp-viewer --no-pager      # should be "active (running)"
```

## 7. Put nginx in front (large-upload tuning)

```bash
sudo cp /opt/whatsapp-viewer/deploy/nginx-whatsapp-viewer.conf \
        /etc/nginx/sites-available/whatsapp-viewer
sudo ln -sf /etc/nginx/sites-available/whatsapp-viewer /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Visit **`http://<your-ip>/`** — the panel loads. Upload a chat export .zip.

## 8. (Optional) HTTPS with a domain

Point a domain's A record at the IP, set `server_name` in the nginx conf, then:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d wa.yourdomain.com
```
Certbot auto-adds the 443 server block and renews automatically.

---

## Updating later

```bash
cd /opt/whatsapp-viewer && git pull
cd backend && ./.venv/bin/pip install -r requirements.txt
sudo systemctl restart whatsapp-viewer
```

## Troubleshooting

- **Page doesn't load:** re-check both firewall layers (step 2). The iptables step is
  the usual culprit on Oracle Ubuntu images.
- **`413 Request Entity Too Large`:** nginx `client_max_body_size` — the provided
  conf sets it to `0` (unlimited). Confirm the conf is the active one.
- **Upload dies partway on huge files:** raise the timeouts in the nginx conf, and
  consider the resumable-upload option (ask; tus protocol) so uploads can resume.
- **Disk full:** media lives under `WA_STORAGE_DIR`; grow/attach a bigger block volume.
- **Logs:** `journalctl -u whatsapp-viewer -f` (app) and `/var/log/nginx/error.log`.
```

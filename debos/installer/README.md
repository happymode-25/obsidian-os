# Obsidian OS — guided installer (Calamares)

Phase 1.4 deliverable. The debos recipe produces a *live* ISO; `calamares`
gives the installed-system path: language → keyboard → timezone → partition
(LUKS2) → user → bootloader (systemd-boot + Secure Boot enrollment) → reboot
into the first-boot wizard (`scripts/firstboot-wizard`).

## Layout

```
debos/installer/
├── settings.conf          # Calamares session config (view + exec order)
└── modules/
    ├── partition.conf     # LUKS2 + guided partitions (root:/home:/var-lib)
    ├── bootloader.conf    # systemd-boot + Secure Boot
    └── users.conf         # admin user, password policy
```

## Wiring into the ISO

- The calamares config root is packed into the live rootfs:
  `debos/overlays-src/common/etc/calamares/**`
- Packaging: `obsidian-installer` metapackage (add to `PACKAGES` table in
  `scripts/scaffold-packages.py`, Depends: `calamares`, `cryptsetup`,
  `dosfstools`, `sbctl`, `systemd-boot`).
- Boot menu gets an "Install Obsidian OS" entry alongside the live session.

## Security properties the installer must preserve

1. **LUKS2 (Argon2id)** on `/`, `/home`, `/var/lib/libvirt` — separate
   containers, mounted explicitly in generated fstab.
2. **TPM2 auto-unlock opt-in** — post-install hook:
   `systemd-cryptenroll --tpm2-device=auto` for the root container.
3. **Secure Boot** — keys created/enrolled at install
   (`scripts/boot-keys.sh enroll`) and the UKI signed before reboot.
4. No "reset password" backdoors in the installed system; recovery happens
   through TPM/keys or the live ISO, never a hidden shell.
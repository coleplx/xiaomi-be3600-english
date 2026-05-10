# Xiaomi BE3600 Router — English Translation

Translates the Xiaomi BE3600 router web UI from Chinese to English.  
Uses LuCI's i18n system (`.lmo` files) + squashfs overlay bind-mounts for persistence.

## Quick Start

```bash
# 1. Copy and edit credentials
cp .env.example .env
# Edit .env with your router IP and password

# 2. Deploy
./deploy.sh
```

This builds `base.en.lmo` from `base.en.po`, uploads to the router, and installs.

## How It Works

Xiaomi routers use **squashfs** (read-only root filesystem). The install script uses **bind-mounts** to overlay writable copies from `/data/lang_patch/` onto the read-only directories:

```
/usr/lib/lua/luci/  →  bind-mounted from /data/lang_patch/luci/
```

This makes template and i18n changes persistent across reboots (via UCI firewall include + cron).

## Files

| File | Purpose |
|------|---------|
| `i18n/base.en.po` | **Source of truth** — all Chinese→English translations (1600+ entries) |
| `i18n/base.en.lmo` | Binary LMO built from the PO (LuCI i18n format) |
| `scripts/build_lmo.py` | Converts PO → LMO using SuperFastHash |
| `scripts/po2lmo.py` | LMO library (format reverse-engineered from XiaoMi LuCI) |
| `scripts/template_patcher.py` | Scans templates for unwrapped Chinese text and wraps with `<%: %>` tags |
| `payload/install_lang.sh` | Router-side script: overlay, LMO install, UCI config, persistence |
| `deploy.sh` | Orchestrator: build → upload (`scp -O`) → install |

## Updating Translations

Edit `i18n/base.en.po`, then:

```bash
./deploy.sh --upload-only   # rebuild LMO + upload (no reinstall)
```

Or full redeploy:

```bash
./deploy.sh
```

## Commands

```bash
./deploy.sh                 # Full: build LMO → upload → install
./deploy.sh --upload-only   # Build + upload only
./deploy.sh --status        # Show router language state
./deploy.sh --uninstall     # Remove English, restore Chinese
```

## Template Patching

Some Chinese text is hardcoded in HTML templates (not in `<%: %>` tags).  
Use `template_patcher.py` to find and wrap them:

```bash
# Local scan
python3 scripts/template_patcher.py scan <directory>

# Apply on router (after deploy)
ssh root@192.168.31.1 'python3 /data/lang_patch/template_patcher.py patch /data/lang_patch/luci/view/ --wet'
```

Then add the new strings to `base.en.po` and redeploy.

## Requirements

- `sshpass` (for automated SSH/SCP)
- Python 3.x
- Router must have SSH enabled and accessible
- Router must have `/data` partition (UBIFS, writable)

## Reusing for Other Routers

1. Extract `<%: %>` strings from the new router's templates
2. Diff against `base.en.po` to find new/missing strings
3. Add translations to a new PO file
4. Adjust `payload/install_lang.sh` if directory structure differs
5. Run `deploy.sh`

## License

MIT

## Credits

- `scripts/po2lmo.py` from [xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher)  
  SuperFastHash algorithm by Paul Hsieh (LGPLv2.1)
- Install/overlay approach inspired by xmir-patcher's `lang_patch.sh`

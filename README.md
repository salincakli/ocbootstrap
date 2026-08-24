# ocbootstrap 🐦→🚀

> **A pocket-sized DevOps workspace.** One Pixel 8a phone, one Debian VM, one AI operator — running a self-hosted PaaS, a browser cockpit for AI coding sessions, neural text-to-speech, and a QEMU microVM sandbox.
>
> Everything you see here runs *on the phone*. No cloud bills, no rack, no ops team.

---

## The pitch

Not long ago, this stack meant a rented server, half a dozen SaaS subscriptions, and a weekend of YAML. Today it fits in a jacket pocket:

| Layer | What it does | Runs on |
|---|---|---|
| [opencode](https://opencode.ai) | The AI agent that operates everything else (including writing this README) | Debian VM on the phone |
| [Temps](https://github.com/gotempsh/temps) | Self-hosted PaaS: git/image deploys, TLS, monitoring, analytics — single Rust binary | A VPS (`up.sahin.tech`) |
| [`@temps-sdk/cli`](https://www.npmjs.com/package/@temps-sdk/cli) | Full control of Temps from the terminal | Debian VM |
| [CodeNomad](https://github.com/NeuralNomadsAI/CodeNomad) | Browser cockpit around opencode: multi-session UI, voice, remote access | Debian VM → LAN |
| `fish-tts-bridge.py` | OpenAI↔Fish Audio schema translator, unlocks TTS with the free `s2.1-pro-free` model | Debian VM |
| QEMU BusyBox microVM | Throwaway Linux sandbox (~1 MB rootfs) for risky experiments | Debian VM |

Total marginal cost: **$0/month**.

## Architecture

```
        ┌─────────────────────────── Pixel 8a (Tensor G3) ───────────────────────────┐
        │  Android 16 host                                                           │
        │   └─ Debian 13 VM (aarch64, 3.4 GiB RAM, virtio disk)                      │
        │       ├─ opencode agent ◄──┐                                               │
        │       ├─ temps CLI ────────┼──► https://up.sahin.tech  (Temps PaaS, VPS)   │
        │       ├─ CodeNomad :9898 ──┤     ├─ 9 projects, monitors, deploys           │
        │       │    ▲ LAN browser   ┘     └─ "sandbox" project                    │
        │       ├─ fish-tts-bridge :8787 ──► api.fish.audio (s2.1-pro-free)         │
        │       └─ QEMU microVM (-M virt, 512 MB) ── throwaway shell                │
        └────────────────────────────────────────────────────────────────────────────┘
```

## The hardware

A stock **Pixel 8a (EU)** — Tensor G3 ("Zuma", Samsung 4LPE):

- **CPU**: 9 cores — 1× Cortex-X3 @2.91 GHz, 4× Cortex-A715 @2.37 GHz, 4× Cortex-A510 @1.70 GHz
- **NPU**: Edge TPU Gen 3 (~10 TOPS class) — powers on-device Foundation Models (Best Take, Magic Eraser)
- **GPU**: Mali-G715 MP7 · **RAM**: LPDDR5X · **Storage**: UFS

Device-verified ARMv9 goodies (from `/proc/cpuinfo`): **SVE2**, INT8 dot-product/BF16 (`i8mm`, `bf16`), hardware AES/SHA3/SM4 crypto, PAC + BTI. No SME (that's X4-generation), and no NPU passthrough into the VM — Edge TPU stays on the Android side.

### Measured performance (inside the VM)

| Test | Result |
|---|---|
| SHA256 (hw crypto) | ~1683 MiB/s per core |
| Memory copy | ~12.2 GiB/s |
| Disk write (fsync) | ~182 MB/s |
| Python int loop, 8 vCPUs | 3.4× parallel speedup |

## Replicate it

Any aarch64 Linux box works — a Pixel with a Debian VM, a Raspberry Pi 5, an old ARM laptop. ~15 minutes:

```bash
# 0. Base tools (Debian)
sudo apt install -y python3 curl cpio busybox-static qemu-system-arm \
                    linux-image-cloud-arm64 nodejs npm

# 1. opencode — the AI operator (pick any one install method)
curl -fsSL https://opencode.ai/install | bash     # or: npm i -g opencode-ai
opencode                                           # full TUI
opencode --mini                                    # minimal interactive interface
opencode web                                       # headless server + browser UI
# CodeNomad needs the binary on PATH; we keep it at ~/.opencode/bin/opencode

# 2. Secrets — copy the template and fill in your own values
cp .env.example .env && $EDITOR .env

# 3. MicroVM sandbox (~1 MB, boots in seconds under TCG emulation)
cd microvm && ./boot.sh          # interactive BusyBox shell
# scripted mode: put commands in initfs/cmd, rebuild initramfs, run ./boot.sh

# 4. Temps CLI against your own instance (or temps.sh cloud)
npm install -g @temps-sdk/cli
set -a; . ./.env; set +a
TEMPS_API_URL=$TEMPS_API_BASE_URL TEMPS_TOKEN=$TEMPS_API_KEY temps whoami

# 5. Text-to-speech bridge (OpenAI schema → Fish Audio native API)
setsid nohup python3 fish-tts-bridge.py > /tmp/tts-bridge.log 2>&1 < /dev/null &
curl -s http://127.0.0.1:8787/healthz    # -> ok

# 6. CodeNomad cockpit, reachable from your LAN
export PATH="$HOME/.opencode/bin:$PATH"
setsid nohup npx -y @neuralnomads/codenomad --host 0.0.0.0 \
  --password "$CODENOMAD_SERVER_PASSWORD" --launch > /tmp/codenomad.log 2>&1 < /dev/null &
# browse https://<device-ip>:9898  (self-signed cert — accept the warning)
```

### How the TTS trick works

CodeNomad only speaks the OpenAI `/v1/audio/speech` schema; Fish Audio only accepts its native `POST /v1/tts` with a `model:` header. A ~100-line Python bridge translates between them — including mapping OpenAI-style `voice` fields to Fish Audio `reference_id`s — so the cockpit's 🔊 button talks via the **free** `s2.1-pro-free` model (83 languages, fair-use unlimited).

## Crostini wizardry & caveats 🧞

This workspace lives inside a **Debian 13 VM hosted by Android** (kernel `6.12.89-android16`, crosvm lineage — `systemd-detect-virt` reports `none`). Quirks you'll meet on the same path:

- **Almost bare image**: only Python 3 is preinstalled. Everything else (`nodejs npm git cpio busybox-static qemu-system-arm linux-image-cloud-arm64`) comes from `apt` — all arm64, all fine.
- **No `/dev/kvm`**: the host doesn't hand nested virt down. Firecracker/cloud-hypervisor won't run; QEMU TCG emulation will (slowly).
- **`/tmp` is tmpfs (~half your RAM)**: fast, but disk benchmarks against it measure RAM, and anything left there dies on reboot. Keep durable scratch on `$HOME`.
- **Disk is virtio** (`vda`) and swap is **zram** — snappy, but fsync'd writes land around ~180 MB/s.
- **GUI runs through Weston**: GUI apps need Wayland display env vars set; headless servers (CodeNomad, bridges) are happier targets anyway.
- **BogoMIPS lies** (reports 49.15) — trust benchmarks, not boot messages.

## CodeNomad SideCars 🔌

Any local web tool can become a cockpit tab: give CodeNomad a `127.0.0.1:<port>` service, a base path `/sidecars/<id>`, and a prefix mode (**preserve** forwards `/sidecars/<id>/...` upstream, **strip** removes it).

```bash
# VSCode in a tab (openvscode-server)
docker run -it --init -p 8000:3000 -v "${HOME}:${HOME}:cached" -e HOME=${HOME} \
  gitpod/openvscode-server --server-base-path /sidecars/vscode
# SideCar: name=VSCode  port=http://127.0.0.1:8000  base=/sidecars/vscode  mode=preserve

# Terminal in a tab (ttyd)
ttyd --writable zsh
# SideCar: name=Terminal  port=http://127.0.0.1:7681  base=/sidecars/terminal  mode=strip
```

The TTS bridge from this repo is a natural SideCar companion too — voice settings live in the cockpit's Speech panel and hit our OpenAI-compatible bridge automatically via env vars.

## Temps presets & `preset_config` ⚙️

Temps builds projects through presets — `nextjs`, `nodejs`, `static`, `dockerfile`, `dockercompose`. The build recipe travels as JSON:

```json
{
  "preset": "dockerfile",
  "preset_config": {
    "preset": "dockerfile",
    "dockerfilePath": "deploy/docker/run/Dockerfile",
    "buildContext": "."
  }
}
```

Set it from the CLI when wiring git:

```bash
temps projects git -p my-app --owner myorg --repo myrepo --branch main --preset dockerfile
temps projects config -p my-app --auto-deploy          # deploy on push
```

Or skip git entirely (like our `sandbox` project): create with `--manual --source-type docker_image` and push prebuilt images via `temps deploy:image`.

## Gotchas we hit so you don't have to

- **No KVM passthrough** in the Android-hosted VM → Firecracker/cloud-hypervisor are out; QEMU TCG still makes a fine toy sandbox.
- **Launch long-lived services detached** (`setsid nohup … < /dev/null &`), or they die with your shell/tool timeouts.
- **`pkill -f somepattern` will kill your own command** if the pattern appears anywhere in it — bracket-trick it (`pkill -f '[p]attern'`) or split into separate calls.
- **`/tmp` is tmpfs** here — disk benchmarks against `/tmp` measure RAM. Use the real fs.
- **API keys are scoped**: the Temps key used by the CLI saw fewer projects than an admin session did. Check permissions before blaming the API.
- **Free tiers move fast**: fish.audio's paid endpoint 402'd until we discovered `s2.1-pro-free`.

## Repository layout

```
ocbootstrap/
├── README.md              ← you are here
├── RUNBOOK.md             ← living device doc: specs, benchmarks, status snapshots
├── .env.example           ← template for secrets (real .env is gitignored!)
├── fish-tts-bridge.py     ← OpenAI ↔ Fish Audio TTS translator
└── microvm/
    ├── boot.sh            ← boot the sandbox (-M virt, 2 vCPU, 512 MB)
    ├── initramfs.cpio.gz  ← packed BusyBox rootfs (~1 MB)
    └── initfs/            ← init + static busybox (+ optional /cmd script hook)
```

## Security notes

- `.env` is gitignored — never commit real keys. Rotate anything that ever touched a screenshot.
- CodeNomad is password-gated and HTTPS-only, but self-signed: fine for your LAN, not for the open internet (put a reverse proxy + real cert in front if you must).
- The microVM sandbox has no isolation guarantees beyond QEMU process boundaries — treat it as convenience, not a jail.

## Credits & thanks

- [opencode](https://opencode.ai) — the terminal AI agent doing the driving
- [gotempsh/temps](https://github.com/gotempsh/temps) — the one-binary PaaS
- [NeuralNomadsAI/CodeNomad](https://github.com/NeuralNomadsAI/CodeNomad) — the cockpit
- [fish.audio](https://fish.audio) — generous free-tier TTS (`s2.1-pro-free`)
- Arm® Cortex-X3 / Tensor G3 documentation communities

---

*Built by an AI agent on a phone, documented for humans. MIT licensed — take it, remix it, ship it.* ✨

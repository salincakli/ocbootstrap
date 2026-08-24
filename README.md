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

### Teach your agent everything: install the skill 🧠

This repo ships its knowledge as an [opencode skill](https://opencode.ai/docs/skills/) — stack commands, device quirks and all ten hard rules, condensed for any agent session:

```bash
# project-scoped — already at .opencode/skills/ocbootstrap/, just run opencode in this repo:
opencode

# or install globally, available from any directory:
mkdir -p ~/.config/opencode/skills
cp -r .opencode/skills/ocbootstrap ~/.config/opencode/skills/
```

Skills load at startup — restart opencode after copying.

### How the TTS trick works

CodeNomad only speaks the OpenAI `/v1/audio/speech` schema; Fish Audio only accepts its native `POST /v1/tts` with a `model:` header. A ~100-line Python bridge translates between them — including mapping OpenAI-style `voice` fields to Fish Audio `reference_id`s — so the cockpit's 🔊 button talks via the **free** `s2.1-pro-free` model (83 languages, fair-use unlimited).

## opencode as a service & preemptive tricks ⚡

opencode isn't just a TUI — it's a server you can keep running and reuse:

```bash
# Headless service mode
setsid nohup opencode serve --port 4096 > /tmp/opencode-serve.log 2>&1 < /dev/null &
opencode attach http://127.0.0.1:4096        # reconnect from any terminal

# Browser mode (server + web UI in one)
opencode web

# ACP server for editor integrations (Zed etc.)
opencode acp
```

Preemptive-work patterns that pay off on a pocket datacenter:

- **Keep it warm**: services started with `setsid nohup … < /dev/null &` survive your shell — boot your stack once (serve + bridge + cockpit), attach on demand.
- **Parallel agents > one busy agent**: open multiple opencode sessions as CodeNomad tabs, each pinned to its own **git worktree** (`codenomad` creates them under `.codenomad/worktrees`) — no merge-gridlock between tasks.
- **Batch the slow stuff**: bake commands into the microVM's `initfs/cmd`, rebuild the initramfs, fire `./boot.sh`, and collect results — emulation runs while you do something else.
- **Watch tasks, not terminals**: CodeNomad surfaces background tasks and child sessions, so long builds can run unattended while you queue the next job.
- **Script the agent itself**: every trick on this page was executed by opencode via its CLI tools — CI-style automation is just prompts plus cron.

## Under the hood: this is AVF, not your average chroot 🧞

The Debian VM isn't a container or proot trick — it's Google's **Android Virtualization Framework**: crosvm (the ChromeOS VMM) driven by VirtualizationService, isolated by pKVM. The stock path is the **Terminal app** on any Pixel 6+ running Android 16+ (*Developer options → Linux development environment*); Snapdragon devices only expose protected VMs and are locked out on stock firmware.

Tuning lives in the Terminal app's gear icon:

| Control | Why you care |
|---|---|
| **Memory size** | default is a stingy 1024 MiB — raise it (slider scales ~2/3 of RAM) before running agents + servers |
| **Keep awake** | screen-off survival timer (up to 1 day) — long builds need it, battery suffers |
| **Port control** | gate which VM ports are reachable |
| **Graphics acceleration** | Pixel 10 Pro only; everyone else gets the software renderer |

Kernel-level surprises we've confirmed or inherited from the field:

- **`CONFIG_SYSVIPC` is off** — `fio` won't run, some multiprocessing shims break; benchmark with `dd`, parallelize with forks
- **nftables silently fails** — use `iptables-legacy` (`update-alternatives --set iptables /usr/sbin/iptables-legacy`)
- **Monolithic kernel**: no module loading, `/lib/modules/` empty — what's compiled in is all you get
- **Unclean shutdown = "VM damaged"**, full reinstall. Commit early, push often, treat storage as semi-ephemeral
- **VM IP rotates every boot** — never hardcode it (our cockpit URL is a case in point)
- Cellular data needs *Apps → Terminal → Unrestricted mobile data*; Wi-Fi just works
- Security defaults are loose: `droid` has NOPASSWD sudo and a known cloud-init password — `sudo passwd droid` first

## ADB superpowers: phone hardware from inside the VM 📡

The VM is sandboxed away from sensors and cameras — but **wireless ADB bridges that gap**, turning the phone into a peripheral farm for your workloads:

1. Phone: *Developer options → Wireless debugging → Pair device with pairing code*
2. In the VM: `adb pair <phone-wifi-ip>:<pair-port> <code>` (use split-screen — the code expires fast)
3. `adb connect <phone-wifi-ip>:<port>` — port rotates per session; pairing itself survives VM reboots

Real-world workloads and what they demand:

| Workload | Command | Requirement / gotcha |
|---|---|---|
| Battery-aware scheduling | `adb shell dumpsys battery` | none — level, voltage, temperature in one shot; pause heavy jobs under 20% |
| Thermal throttle guard | `adb shell dumpsys thermalservice` | none — check before benchmarks (our Tensor runs hot) |
| Host log triage | `adb logcat` | none — Android logs stream straight into agent sessions |
| Sensor inventory (42!) | `adb shell dumpsys sensorservice` | enumeration only; live X/Y/Z streaming still needs a helper app or `getevent` parsing |
| GPS fix | `adb shell dumpsys location \| grep last` | location services on; ~11 m accuracy observed |
| Screenshot / screen record | `screencap -p` · `screenrecord --time-limit N` | pulls to VM at ~80 MB/s — great for docs and bug reports |
| UI automation | `adb shell input tap/swipe/text` | coordinate-based; 10-point multitouch reported |
| Drive a browser test on the host | `am start -a android.intent.action.VIEW -d <url>` | pairs beautifully with a Temps deployment: deploy → open on same device → screencap proof |
| Camera capture | `am start -a IMAGE_CAPTURE --eu output file:///sdcard/photo.jpg` | must pass an output URI; plain capture gives you a viewfinder but no file |

Stack these: our agent can run a Temps deploy, watch battery/thermal headroom, launch the result on the host browser, screenshot it, and attach the PNG to the PR — all from inside the VM.

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

### More mileage from the same binary 🎯

Every feature below ships inside Temps already — no add-on services, no extra invoices:

- **Push-to-deploy portfolio** — one project per repo; `nextjs`/`nodejs` presets build straight from git, custom domains get Let's Encrypt certificates issued automatically
- **CI-built images without a registry middleman** — build in GitHub Actions, push the image with `temps deploy:image`, done (our `sandbox` project lives this way)
- **Staging ↔ production symmetry** — clone a project, point it at a `staging` branch, flip `--auto-deploy` off and promote manually when QA passes
- **Monitoring without Pingdom** — built-in monitors watch every deployed service; pair them with ADB battery/thermal checks for full pocket-datacenter observability
- **Analytics without the cookie banner** — first-party, privacy-friendly stats per project; retire Plausible/Fathom/GA4 entirely
- **Hackathon & client-demo mode** — `--manual` project + image push puts a demo on a real HTTPS domain in minutes, deleted the moment the meeting ends
- **One VPS, many tenants** — a single Rust binary hosts all of it; no per-seat math, no credit spreadsheets

### Real-world duty: what the casual stack charges 💸

Take one plausible workload — a freelancer running three client sites, two side-project APIs, staging copies of each, plus monitoring and analytics:

| # | Job to be done | Casual stack | Street price/mo | This stack | Why ours is $0 |
|---|---|---|---|---|---|
| 1 | Next.js client apps ×3 | Vercel Pro (1 seat) | ~$20 | `nextjs` preset | builds run on the box you already have |
| 2 | Static marketing sites ×3 | Netlify Pro | ~$20 | `static` preset | no bandwidth credits to ration |
| 3 | Side-project APIs ×2 | Railway Hobby + usage overage | ~$15–35 | `dockerfile` preset | idle containers don't bill by the GB-hour here |
| 4 | Staging environments ×5 | separate paid tier / per-env pricing | ~$10–20 | cloned project, `--auto-deploy` off | staging is just another project |
| 5 | Deploy previews per PR | Netlify credits (15/deploy) | metered | git integration | every push is a full deploy anyway |
| 6 | Uptime monitors | Pingdom Starter | ~$15 | built-in monitors | ships in the binary |
| 7 | Privacy-friendly analytics | Plausible Starter → Growth | ~$9–19 | built-in analytics | first-party, per-project, cookie-free |
| 8 | TLS certificates | paywalled tiers / certbot babysitting | $0–10 | automatic Let's Encrypt | issued per domain on deploy |
| | **Monthly damage** | | **~$90–140** | **~$0 marginal** | |

#### Where casual stacks hide the knife 🔪

- **Per-seat math**: on Vercel/Netlify Pro, *every* dev who pushes to a connected repo becomes a ~$20/member invoice — a 5-person agency pays $160+/mo before a single byte is served
- **Credit opacity**: Netlify's 2025+ credit model meters deploys, bandwidth, functions and even PR previews separately — predicting a bill needs a spreadsheet
- **Idle ≠ free**: Railway bills resources per second whether traffic arrives or not — one sleepy 1 vCPU / 1 GB service runs ~$30/mo at utility rates
- **Feature paywalls**: server-side analytics is a $9/site add-on; staging tiers, log retention and SLAs all live above the entry price
- **Overage roulette**: a front-page-of-Hacker-News day can turn your "free" tier into an invoice

#### Three real-world profiles 📊

| Profile | Stack shape | Casual stack/mo | This stack/mo | Kept per year |
|---|---|---|---|---|
| **Solo hobbyist** | 1 app + 1 static site + analytics | ~$35–45 | ~$0 | ~$420–540 |
| **Freelancer** (table above) | 5 projects + staging + monitors | ~$90–140 | ~$0 marginal | ~$1,080–1,680 |
| **Small team** (5 devs, 10 sites) | per-seat Pro plans + credit overages | ~$200–330 | one shared VPS | ~$2,400–3,900 |

#### The rest of the stack is a SaaS graveyard 🪦

Temps only retires the hosting invoice — every other tool in this workspace buries its own subscription category:

| Our gear | SaaS it deprecates | Street price avoided/mo |
|---|---|---|
| `opencode` agent (bring-your-own — even free — models) | Copilot Pro · Cursor Pro · ChatGPT Plus as pair-programmer | ~$10–20/dev |
| `opencode serve` + cron ("CI-style automation is just prompts plus cron") | Zapier/Make glue automation, paid CI runner minutes | ~$20–30 |
| CodeNomad cockpit (multi-session UI over LAN HTTPS) | GitHub Codespaces hours, ngrok/tunneling Pro tiers, remote-desktop dev tools | ~$8–20 |
| `fish-tts-bridge.py` → free `s2.1-pro-free` model | ElevenLabs / OpenAI TTS credits behind any voice feature | ~$5–22 |
| QEMU microVM sandbox (~1 MB rootfs, boots in seconds) | disposable cloud VMs & sandbox-as-a-service for risky experiments | ~$4–15 |
| ADB hardware bridge (sensors, GPS, camera, screenshots) | device-farm smoke tests (BrowserStack-class app testing) | ~$12–39 |
| **Subtotal** | | **~$60–145** |

#### Grand total, all subscriptions dead ☠️

For the freelancer workload above, the full casual stack — hosting *plus* tooling — ran **~$150–285/month**. This stack runs it at **~$0 marginal** (+ an optional $4–6/mo VPS under Temps):

| Profile | Casual stack, all-in/mo | This stack/mo | Kept per year |
|---|---|---|---|
| Solo hobbyist | ~$95–125 | ~$0 | ~$1,100–1,500 |
| Freelancer | ~$150–285 | ~$0 marginal | ~$1,800–3,400 |
| Small team (5 devs) | ~$350–600 | one shared VPS | ~$4,200–7,200 |

Even counting a dedicated small Hetzner-class box (~$4–6/mo), net savings land around **$1,000–1,500/year solo, $1,700–3,300/year freelancing, $4,100+/year for a team** — enough to buy the Pixel 8a running this entire show two to four times over, every single year.

*(Street prices rounded from vendor pages, verified August 2026 — Copilot Pro $10, Cursor Pro $20, Plausible from $9, Pingdom from $15, Netlify/Vercel Pro $20/seat, Railway Hobby $5. Your mileage will vary; your invoices won't.)*

## Production proof: we moved a live API onto Temps 🏭

This stack isn't a toy demo — the same weekend it was built, it absorbed a **full production
migration**: a paid-customer API ([surstreaming.live](https://surstreaming.live), TikTok live-stream
tooling, SSE-heavy, 1 paying customer + 30+ trials) moved off Coolify-on-Vultr onto Temps-on-UpCloud,
executed end-to-end by an AI operator over SSH and REST APIs across three servers.

### The architecture we landed on

```
api.surstreaming.live ──CNAME──► UpCloud Managed LB (Essentials tier — $0/mo)
                                   │  TLS termination (LE bundle)
                                   ├── :443 → Temps origin :8443   ✅ live
                                   ├── :80  → Temps ACME/redirects ✅ live
                                   └── old provider member: kept warm, DISABLED
                                        (rollback = two API calls, zero DNS changes)
```

The Essentials load balancer is **permanently free** (UpCloud Essentials program) — failover,
health checks and instant member toggles for $0. Rollback is no longer a DNS wait; it's an
enable/disable flip.

### Timeline of one evening

| Time | Event |
|---|---|
| T+0 | Found the target: a half-finished Aug-10 Temps import, disk 100% full |
| +15 min | 84 GB of stale Docker images pruned; crash-looping timescaledb recovered |
| +1 h | Backend deployed from repo Dockerfile after fixing preset config, exposedPort, and DB hostnames |
| +2 h | Free LB provisioned via API, LE cert chain uploaded as bundle, DNS flipped through it |
| same night | **Customer stream running on the new stack** — health, OAuth, SSE all verified |

### The incident that justified the whole runbook

Mid-migration, both database containers (and volumes) got deleted by accident. Total recovery
time: **~5 minutes** — because the migration runbook had already saved a config snapshot and a
fresh `pg_dump`. Recreate containers from inspect JSON → restore dump → restart app → 39 users,
0 errors. The nightly backup cron that exists today was born that night.

### Gotchas worth their weight in gold (server-side edition)

| Gotcha | Fix |
|---|---|
| Temps' python preset builds via Nixpacks (`uv sync` fails) | use the repo's own Dockerfile preset with `dockerfilePath` in `preset_config` |
| Environment-level `exposedPort` must match the app port or readiness probes never pass | set per-environment, not just project |
| Docker-DNS names don't resolve cross-node | drain worker nodes that can't run the app, or fix env hosts |
| Custom domains: proxy rejects unknown-SNI handshakes until cert exists | register domain (`POST /api/domains`, http-01) → provision → finalize; needs a port-80 frontend path to the origin |
| UpCloud LB health checks can't send vhost SNI | strict-TLS origins need `tcp` checks or an SNI-aware shim |
| Cert bundles are base64 PEMs — leaf split from intermediates, newline-joined | encode carefully or validation rejects |
| IPv6-only worker can't reach relay (no AAAA) | join in direct mode over private network + `/etc/hosts` pin |
| SELinux blocks scp'd binaries in systemd units | `chcon -t bin_t` |
| Out-of-band `docker restart` latches UI into "degraded" | always redeploy via pipeline |

Full runbook lives in the ops workspace; the pattern generalizes to any Temps deployment.

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
├── .opencode/
│   └── skills/
│       └── ocbootstrap/SKILL.md ← installable opencode skill: stack ops, condensed
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

## Related links

- [claude-code-android AVF guide](https://github.com/ferrumclaudepilgrim/claude-code-android/blob/main/docs/avf-guide.md) — deep dive into the Android Virtualization Framework that makes the Debian VM possible

## Credits & thanks

- [opencode](https://opencode.ai) — the terminal AI agent doing the driving
- [gotempsh/temps](https://github.com/gotempsh/temps) — the one-binary PaaS
- [NeuralNomadsAI/CodeNomad](https://github.com/NeuralNomadsAI/CodeNomad) — the cockpit
- [fish.audio](https://fish.audio) — generous free-tier TTS (`s2.1-pro-free`)
- [surstreaming.live](https://surstreaming.live) — production API running on this exact stack since August 2026
- [ferrumclaudepilgrim/claude-code-android](https://github.com/ferrumclaudepilgrim/claude-code-android) — the AVF field guide that shaped our "Under the hood" and ADB sections
- [Arm® Cortex-X3 / Tensor G3 documentation communities](https://www.androidauthority.com/pixel-8-tensor-g3-specs-3331398/)

---

*Built by an AI agent on a phone, documented for humans. MIT licensed — take it, remix it, ship it.* ✨

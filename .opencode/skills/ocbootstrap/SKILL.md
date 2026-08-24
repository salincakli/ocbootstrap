---
name: ocbootstrap
description: Operate and troubleshoot the ocbootstrap pocket datacenter — a Pixel 8a (Tensor G3) running a Debian 13 AVF VM with Temps PaaS deploys, CodeNomad cockpit, fish-tts TTS bridge, and a QEMU BusyBox microVM sandbox. Use when deploying via the temps CLI, launching or stopping any of these services, using wireless ADB from inside the VM, benchmarking the device, operating the production server (up.sahin.tech: pipelines, env vars, custom domains, TLS, load balancer, DB/Redis recovery), or when hitting its known gotchas (no KVM, detached services, VM IP rotation, tmpfs /tmp).
---

# ocbootstrap — pocket datacenter ops

One Pixel 8a phone runs a self-hosted PaaS, an AI cockpit, neural text-to-speech and a throwaway sandbox. Everything operates from inside the Debian VM; total marginal cost ~$0/month. Secrets live in `.env` (template: `.env.example`); the real file is gitignored and never committed.

## Stack map

| Piece | What it does | Where |
|---|---|---|
| opencode | The AI agent operating everything else | Debian VM |
| Temps | PaaS: git/image deploys, TLS, monitoring, analytics | a VPS, driven by `temps` CLI |
| CodeNomad | Browser cockpit: multi-session UI, voice, LAN access (:9898) | Debian VM |
| `fish-tts-bridge.py` | OpenAI↔Fish Audio schema translator (:8787), free `s2.1-pro-free` model | Debian VM |
| QEMU microVM | ~1 MB BusyBox rootfs sandbox, boots in seconds under TCG | Debian VM |

## Device envelope (device-verified)

- Pixel 8a (EU) · Tensor G3 "Zuma", Samsung 4LPE · 9 cores (1× Cortex-X3 @2.91 GHz, 4× A715 @2.37 GHz, 4× A510 @1.70 GHz) · Mali-G715 MP7 · LPDDR5X · UFS
- Guest: Debian 13, kernel `6.12.89-android16`, 3.4 GiB RAM + zram swap, virtio `vda`
- ARMv9 features from `/proc/cpuinfo`: SVE2, INT8 dot-product/BF16 (`i8mm`, `bf16`), hw AES/SHA3/SM4 (~1683 MiB/s SHA256/core), PAC + BTI. No SME (X4-generation). **No NPU passthrough** — Edge TPU stays on the Android host; use CPU vector paths in-VM
- Measured in VM: memcopy ~12.2 GiB/s, fsync'd writes ~182 MB/s, Python loop 3.4× speedup across 8 vCPUs (scheduling cap)
- BogoMIPS reports 49.15 and is wrong — trust benchmarks, not boot messages

## Workflows

### MicroVM sandbox
```bash
cd microvm && ./boot.sh          # interactive BusyBox shell (-M virt, 2 vCPU, 512 MB)
# scripted mode: put commands in initfs/cmd, rebuild initramfs, run ./boot.sh
```

### Temps deploy (git or image)
```bash
set -a; . ./.env; set +a
temps projects git -p my-app --owner myorg --repo myrepo --branch main --preset dockerfile
temps projects config -p my-app --auto-deploy            # deploy on push
# skip git entirely: manual project + prebuilt image
TEMPS_API_URL=$TEMPS_API_BASE_URL TEMPS_TOKEN=$TEMPS_API_KEY temps deploy:image --image <img> -p sandbox -y
```
Presets travel as JSON `preset_config` (`nextjs`, `nodejs`, `static`, `dockerfile`, `dockercompose`). Staging = cloned project with `--auto-deploy` off.

### Cockpit + voice (always detached — see hard rule 1)
```bash
setsid nohup python3 fish-tts-bridge.py > /tmp/opencode/tts-bridge.log 2>&1 < /dev/null &
curl -s http://127.0.0.1:8787/healthz    # -> ok
export PATH="$HOME/.opencode/bin:$PATH"
setsid nohup npx -y @neuralnomads/codenomad --host 0.0.0.0 \
  --password "$CODENOMAD_SERVER_PASSWORD" --launch > /tmp/opencode/codenomad.log 2>&1 < /dev/null &
# browse https://<device-ip>:9898 (self-signed cert — accept warning)
```
CodeNomad speaks OpenAI `/v1/audio/speech`; the bridge maps `voice` → Fish Audio `reference_id` and calls the native API. Env: `OPENAI_BASE_URL=http://127.0.0.1:8787/v1`.

### opencode as a service
```bash
opencode serve --port 4096               # then: opencode attach http://127.0.0.1:4096
opencode web                             # headless server + browser UI in one
opencode acp                             # ACP server for editor integrations (Zed etc.)
```
Parallel work: multiple sessions as CodeNomad tabs, each pinned to its own git worktree.

### Wireless ADB — phone hardware from inside the VM
1. Phone: *Developer options → Wireless debugging → Pair device with pairing code*
2. `adb pair <phone-ip>:<pair-port> <code>` (split-screen; code expires fast)
3. `adb connect <phone-ip>:<port>` — port rotates per session, pairing survives reboots

Useful reads: `dumpsys battery` (pause jobs under 20%), `dumpsys thermalservice` (before benchmarks), `logcat`, `screencap -p` (~80 MB/s pull), `screenrecord`, `input tap/swipe/text`, `am start` VIEW/CAMERA intents. Chain example: Temps deploy → open result on host browser → screencap → attach PNG to PR.

## Production server ops (`up.sahin.tech`)

Temps runs live production (surstreaming API) here. Operate it through the REST API with an admin key — **never raw `docker restart` on managed containers** (it latches the UI into "degraded"; redeploy instead).

```bash
# redeploy an environment (build cached, ~1-2 min)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"branch":"main","environment_id":8}' https://up.sahin.tech/api/projects/$PID/trigger-pipeline

# set/update an env var, then redeploy to apply
curl -X POST ... /api/projects/$PID/env-vars  -d '{"key":"K","value":"V","environment_ids":[8]}'

# mint admin keys: TEMPS_DATABASE_URL=<control-plane db url> temps api-key --name X --output-format json
```

Server-side gotchas (all hit in production, all expensive):

| Gotcha | Fix |
|---|---|
| python preset builds via Nixpacks and fails | use repo Dockerfile: `preset_config.dockerfilePath` (+ `buildContext`) — may need a direct DB write, the PUT endpoint drops it |
| readiness probes never pass | per-**environment** `exposedPort` must equal the app's listen port (project-level toggle doesn't propagate) |
| app breaks on worker nodes | Docker-DNS names don't resolve cross-node — drain nodes that must stay app-free |
| custom domain 503s / TLS handshake alerts | register domain first: `POST /api/domains` (http-01) → `/provision` → `/order/finalize`; proxy rejects unknown-SNI until cert exists; ACME needs a port-80 path to origin |
| private keys not exportable | `tls_acme_certificates` values are encrypted at rest — renew via independent ACME (acme.sh standalone + temporary LB backend detour) |
| IPv6-only worker can't join cluster | relay has no AAAA — direct mode over private network + `/etc/hosts` pin of control plane; `chcon -t bin_t` the binary or systemd hits SELinux |
| DB health check "down" | prober connects on the loopback port-publish convention (e.g. localhost:5433); recreate container with `-p 127.0.0.1:<port>:5432` |

### Load balancer (UpCloud Essentials — free tier)

- Cert bundles: PEM fields are **base64-encoded**; split leaf vs intermediates; join intermediates with newlines.
- Health checks cannot send vhost SNI → strict-TLS origins need `tcp` checks, or terminate at a local shim that re-proxies with correct SNI.
- No SNI replay to backends either. ACME HTTP-01 requires a port-80 frontend routed to the origin's challenge handler.
- Rollback between providers = flip member `enabled` flags in `PATCH /load-balancer/{uuid}` (send the full backends array). Never enable two members of a single-instance app.

### Recovery pattern (validated by real incident)

When managed DB containers get deleted: restore from config snapshot (`docker inspect` saved beforehand) with identical names/credentials → re-link `container_name` in `external_services` + publish the probe port → `pg_dump` restore → restart app. Keep nightly dumps + config snapshots *before* you need them.

## Hard rules (violating these breaks things)

1. **Detach long-lived services**: `setsid nohup … > log 2>&1 < /dev/null &` or tool timeouts kill them.
2. **No KVM**: Android host doesn't pass through `/dev/kvm`. Firecracker/cloud-hypervisor won't run; QEMU TCG will (slowly).
3. **Unclean shutdown = "VM damaged"**, full reinstall. Commit early, push often, treat storage as semi-ephemeral.
4. **VM IP rotates every boot** — never hardcode it.
5. **`CONFIG_SYSVIPC` is off**: `fio` won't run, some multiprocessing shims break. Benchmark with `dd`, parallelize with forks.
6. **nftables silently fails** — use `iptables-legacy`: `update-alternatives --set iptables /usr/sbin/iptables-legacy`.
7. **Monolithic kernel**: no module loading, `/lib/modules/` empty — compiled-in is all you get.
8. **`pkill -f` kills your own command** if the pattern matches anywhere in it — bracket-trick it: `pkill -f '[p]attern'`.
9. **`/tmp` is tmpfs** (~half RAM): contents die on reboot; disk benchmarks against `/tmp` measure RAM. Durable scratch goes in `$HOME`.
10. **API keys are scoped** — verify permissions before blaming the API. Free tiers move fast: fish.audio's paid endpoint 402s; the free `s2.1-pro-free` model is the reliable path.

## Why this stack exists (cost model)

Deprecates the casual dev SaaS pile — Vercel/Netlify hosting, Railway APIs, Pingdom monitoring, Plausible analytics, Copilot/Cursor seats, ElevenLabs TTS, Codespaces hours, Zapier glue, disposable cloud VMs, device farms. Freelancer-grade workload: ~$150–285/mo casual vs ~$0 marginal here (+ optional $4–6/mo VPS under Temps). Full line-item math lives in the README's cost section.

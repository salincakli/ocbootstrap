# Device Runbook — Pixel 8a (EU) / "droid"

_Last updated: 2026-08-24_

## 1. Identity

| | |
|---|---|
| Device | Google Pixel 8a (EU) |
| SoC | Google Tensor G3 ("Zuma", Samsung 4LPE), model GS301 |
| CPU | 9 cores: 1x Cortex-X3 @2.91 GHz + 4x Cortex-A715 @2.37 GHz + 4x Cortex-A510 @1.70 GHz (DSU-110) |
| GPU | Mali-G715 MP7 @ ~890 MHz (~1.6 TFLOPS FP16) |
| NPU | Edge TPU Gen 3 ("Rio"), ~16 cores @1.12 GHz, ~10 TOPS (third-party estimate, Google unpublished) |
| Memory | LPDDR5X, up to 68 GB/s SoC-level; VM sees 3.4 GiB + 870 MiB zram swap |
| Storage | UFS, exposed to VM as 104 GB virtio `vda` |
| Guest OS | Debian GNU/Linux 13 (trixie), aarch64, kernel `6.12.89-android16` (Android-hosted VM) |

## 2. Measured performance (this VM, 2026-08-24)

| Test | Result |
|---|---|
| Python int loop, single core | 1.61 s/run (~12.4M iters/s) |
| Same across 8 vCPUs | 3.4x speedup (VM scheduling cap) |
| SHA256 (hw crypto) | ~1683 MiB/s per core |
| Memory copy bandwidth | ~12.2 GiB/s (VM-limited vs 68 GB/s SoC peak) |
| Disk write (fsync'd) | ~182 MB/s |
| Disk read | ~4.0 GB/s (page-cache inflated) |

Reference points: Geekbench 6 ≈ 1539–1767 single / 4349–4477 multi (native Android).

## 3. CPU special abilities — Cortex-X3 ("Makalu-ELP", ARMv9.0-A)

Device-verified via `/proc/cpuinfo` Features:

- **SVE2** (128-bit scalable vectors) + NEON — vector-length-agnostic SIMD with predication (`sve sve2 asimdfhm svei8mm svebf16 svesha3 ...`)
- **INT8 dot-product & BF16 ML fast paths** (`i8mm`, `bf16`, `sdot/udot`) — quantized-inference acceleration on CPU
- **Hardware crypto**: AES, PMULL, SHA1/SHA2/SHA3/SHA512, SM3/SM4 (`aes pmull sha1 sha2 sha3 sha512 sm3 sm4`) — drives the 1.7 GB/s hash rate
- **ARMv9 security**: PAC (pointer authentication, `paca pacg`), BTI (`bti`); MTE not exposed in this VM
- Microarchitecture: 6-wide decode / 8-wide dispatch, ~320-entry ROB, AArch64-only
- Not present: SME/SME2 (arrived with Cortex-X4 / ARMv9.2)

## 4. NPU special abilities — Tensor G3 Edge TPU Gen 3

- First-gen on-device "Foundation Models" (shrunken cloud models): Best Take, Magic Eraser, Assistant TTS run locally
- TFLite-style INT8/FP16 inference pipeline alongside GPU/CPU delegate fallback
- AV1 encode (first mobile SoC to do so) + 8K30/4K120 codec blocks share the media pipeline

**Constraint:** the Debian VM has **no NPU passthrough** (no `/dev/apex_*` node) — Edge TPU is only reachable from the Android host. Use CPU SVE2/i8mm paths for in-VM inference.

## 5. Sandboxes

### 5a''. CodeNomad TTS (fish.audio via local bridge)
Fish Audio has no OpenAI-compatible path, so a bridge translates schemas:
`fish-tts-bridge.py` listens on `127.0.0.1:8787`, `POST /v1/audio/speech` → fish `POST /v1/tts` (Model: s1, voice→reference_id).
CodeNomad reads `OPENAI_BASE_URL=http://127.0.0.1:8787/v1` + `OPENAI_API_KEY` from `.env` at launch.
Status: **working** — model header `s2.1-pro-free` (Fish Audio free tier, fair-use). Verified: returns real MP3 audio.

### 5a'. CodeNomad cockpit (LAN service)
`npx @neuralnomads/codenomad --host 0.0.0.0 --password $CODENOMAD_SERVER_PASSWORD --launch`
- LAN URL `https://10.247.33.69:9898` (self-signed cert → accept warning), password in `.env`
- Launch detached (`setsid nohup ... &`) or tool timeouts kill it; log at `/tmp/opencode/codenomad.log`

### 5a. Temps "sandbox" (remote, container-based)
Project ID 12 on up.sahin.tech (manual/docker-image preset, no deployment yet).
Deploy an image: `TEMPS_API_URL=https://up.sahin.tech TEMPS_TOKEN=<key> temps deploy:image --image <img> -p sandbox -y`

### 5b. Local microVM (`~/ocbootstrap/microvm/`)
QEMU TCG emulation — **no KVM** on this device (Android host doesn't pass through `/dev/kvm`), firecracker/cloud-hypervisor unavailable.
- `initfs/` — BusyBox root: static busybox + init (mounts proc/sys/dev, runs `/cmd` if present then powers off, else drops to interactive ash)
- `initramfs.cpio.gz` — ~1 MB packed rootfs
- `boot.sh` — `-M virt -cpu max -smp 2 -m 512M`, Debian cloud kernel `6.12.101+deb13-cloud-arm64`, virtio-net user-mode networking
- Interactive: `./boot.sh`; scripted: put commands in `initfs/cmd`, rebuild initramfs, run `./boot.sh`
- Verified boot: `Linux (none) 6.12.101+deb13-cloud-arm64 aarch64` + shell

## 6. up.sahin.tech — Temps PaaS status snapshot (2026-08-24)

Auth: `~/ocbootstrap/.env` → `TEMPS_API_BASE_URL`, `TEMPS_API_KEY` (Bearer).
Probe: `curl -H "Authorization: Bearer $TEMPS_API_KEY" https://up.sahin.tech/api/projects`

Gateway `/healthz`: ok. 9 projects hosted:

| id | project | svc status | uptime | deploys (ok) | current |
|----|---------|-----------|--------|--------------|---------|
| 3 | wg | operational | 100% | 0 | – |
| 4 | wgsec | operational | 100% | 0 | – |

Notes:
- Monitor states report `unknown` platform-side despite 100%/0% uptime — monitor probes may be misconfigured.
- Latest failure example (fbb #22): external image pull failed — `cr.fluentbit.io/fluent/fluent-bit:latest` → Docker 404.
- Key endpoints: `/api/projects`, `/api/projects/{id}/status`, `/api/projects/{id}/deployments`, `/api/backups/alerts`.

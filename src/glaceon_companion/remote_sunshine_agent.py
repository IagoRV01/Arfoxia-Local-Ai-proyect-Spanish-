"""Narrow, ephemeral Sunshine bridge executed as the desktop user over SSH.

Only status and PIN submission, to literal loopback. No files are written and
no credentials/PINs are printed. Keep this file independent of Arfoxia imports.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sunshine_request(path, credentials, payload=None):
    if path not in {"/api/clients/list", "/api/pin"}:
        raise ValueError("Unsupported Sunshine endpoint")
    username, password = credentials
    authorization = base64.b64encode((username + ":" + password).encode()).decode()
    request = urllib.request.Request("https://127.0.0.1:47990" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Basic " + authorization,
                 "Content-Type": "application/json", "Accept": "application/json"})
    # TLS exception is confined to this loopback service inside authenticated SSH.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    with opener.open(request, timeout=12) as response:
        value = json.loads(response.read(65537))
    if not isinstance(value, dict):
        raise ValueError("Unexpected Sunshine reply")
    return value


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def connection_host():
    tail_ip = ""
    host = ""
    try:
        result = subprocess.run(["tailscale", "status", "--json"], capture_output=True,
            text=True, timeout=3, check=False)
        value = json.loads(result.stdout) if result.returncode == 0 else {}
        if value.get("BackendState") == "Running":
            own = value.get("Self") or {}
            for candidate in own.get("TailscaleIPs", []):
                address = ipaddress.ip_address(candidate)
                if address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10"):
                    tail_ip = str(address)
            name = str(own.get("DNSName") or "").rstrip(".")
            if re.fullmatch(r"[a-zA-Z0-9.-]+\.ts\.net", name):
                host = name
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError, TypeError):
        pass
    if host or tail_ip:
        return host or tail_ip, tail_ip
    try:
        address = ipaddress.ip_address(os.environ.get("SSH_CONNECTION", "").split()[2])
        if address.is_private and not address.is_loopback:
            host = str(address)
    except (ValueError, IndexError):
        pass
    return host, ""


def run(request):
    if not isinstance(request, dict) or set(request) - {"operation", "username", "password", "pin", "name"}:
        raise ValueError("Invalid request")
    operation = request.get("operation")
    if operation not in {"status", "pair"}:
        raise ValueError("Invalid operation")
    username, password = request.get("username", ""), request.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 4096 or ":" in username:
        raise ValueError("Invalid credentials")
    credentials = (username, password) if username and password else None
    if operation == "pair":
        pin, name = request.get("pin"), request.get("name")
        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
            raise ValueError("Invalid PIN")
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise ValueError("Invalid client name")
        if credentials is None:
            return {"success": False, "error": "credentials_required"}
        try:
            value = sunshine_request("/api/pin", credentials, {"pin": pin, "name": name})
            return {"success": value.get("status") is True or value.get("status") == "true"}
        except urllib.error.HTTPError as error:
            return {"success": False, "error": "credentials_invalid" if error.code == 401 else "pairing_failed"}
        except (OSError, ValueError):
            return {"success": False, "error": "pairing_failed"}
    ports = {str(port): port_open(port) for port in (47984, 47989, 48010, 47990)}
    verified = False
    credential_check = "not_configured" if not credentials else "unreachable"
    names = []
    count = 0
    if credentials and ports["47990"]:
        try:
            value = sunshine_request("/api/clients/list", credentials)
            verified = value.get("status") is True or value.get("status") == "true"
            credential_check = "verified" if verified else "invalid_response"
            if verified:
                records = value.get("named_certs", [])
                if isinstance(records, list):
                    for row in records[:100]:
                        if not isinstance(row, dict) or row.get("enabled") is False or row.get("revoked") is True:
                            continue
                        count += 1
                        if isinstance(row.get("name"), str):
                            names.append(row["name"][:64])
        except urllib.error.HTTPError as error:
            credential_check = {401: "unauthorized", 403: "forbidden", 404: "unsupported_api"}.get(error.code, "server_error")
        except OSError:
            credential_check = "unreachable"
        except ValueError:
            credential_check = "invalid_response"
    host, tail_ip = connection_host()
    ready = all(ports[str(port)] for port in (47984, 47989, 48010))
    return {"success": True, "ports": ports, "running": ready, "web_ready": ports["47990"],
        "host": host, "tailscale_ip": tail_ip, "tailscale_ready": bool(tail_ip),
        "credentials_verified": verified, "credential_check": credential_check,
        "paired_clients": count, "paired_device_names": names}


def main():
    try:
        raw = sys.stdin.read(16385)
        if len(raw) > 16384:
            raise ValueError("Request too large")
        result = run(json.loads(raw))
    except Exception:
        result = {"success": False, "error": "bridge_failed"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()

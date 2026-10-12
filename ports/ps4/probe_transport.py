"""Explicit, one-shot delivery of the Arfoxia home-menu capability probe.

No BinLoader 'ping': opening its socket can consume a one-shot listener.
No auto-start, credentials, game plugins, memory offsets or kernel patches.
"""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
from pathlib import Path
import socket

REMOTE = '/data/Arfoxia'
MAX_PRX = 256 * 1024
MAX_PAYLOAD = 64 * 1024
MAX_LOG = 128 * 1024
LIVE_LOADS_DISABLED = True  # System-software crash on 12.52: offline research only.


def require_live_enabled() -> None:
    if LIVE_LOADS_DISABLED:
        raise ValueError('PS4 live probe quarantined after CE-36329-3; no further payload loads')


def read_bounded(ftp: ftplib.FTP, path: str, limit: int) -> bytes:
    content = bytearray()

    def receive(block: bytes) -> None:
        if len(content) + len(block) > limit:
            raise ValueError('Remote file exceeds the diagnostic size limit')
        content.extend(block)

    ftp.retrbinary('RETR ' + path, receive)
    return bytes(content)


def validate(prx: bytes, loader: bytes) -> None:
    # OpenOrbis fake SELF (not an ELF/.oelf); never send an arbitrary binary.
    if not 64 <= len(prx) <= MAX_PRX or prx[:4] != bytes.fromhex('4f153d1d'):
        raise ValueError('Expected a built OpenOrbis PRX')
    if not 64 <= len(loader) <= MAX_PAYLOAD or loader[:1] != b'\xe9':
        raise ValueError('Expected the raw SDK loader, not an ELF')
    for marker in (b'ARFOXIA_LOADER 1', b'SceShellUI', b'/data/Arfoxia/arfoxia_probe.prx'):
        if marker not in loader:
            raise ValueError('Loader is not the scoped Arfoxia capability probe')


def stage(ftp: ftplib.FTP, prx: bytes) -> str:
    require_live_enabled()
    try:
        ftp.cwd(REMOTE)
    except ftplib.error_perm as exc:
        if not str(exc).startswith('550'):
            raise
        ftp.mkd(REMOTE)
        ftp.cwd(REMOTE)
    existing = {name.rsplit('/', 1)[-1] for name in ftp.nlst()}
    if existing.intersection({'arfoxia_probe.prx', 'arfoxia_probe.upload-bin'}):
        raise ValueError('Probe already staged: preserve it; do not overwrite or reload blindly')
    # GoldHEN auto-decrypts .prx on RETR; verify under a neutral suffix first.
    ftp.storbinary('STOR arfoxia_probe.upload-bin', io.BytesIO(prx))
    if read_bounded(ftp, 'arfoxia_probe.upload-bin', MAX_PRX) != prx:
        raise ValueError('FTP readback differs: payload must not be loaded')
    ftp.rename('arfoxia_probe.upload-bin', 'arfoxia_probe.prx')
    return hashlib.sha256(prx).hexdigest()


def verify_staged(ftp: ftplib.FTP, prx: bytes) -> None:
    require_live_enabled()
    # No source overwrite. Restore the name even when verification fails.
    source = REMOTE + '/arfoxia_probe.prx'
    temporary = REMOTE + '/arfoxia_probe.verify-bin'
    names = {name.rsplit('/', 1)[-1] for name in ftp.nlst(REMOTE)}
    if 'arfoxia_probe.verify-bin' in names:
        raise ValueError('An interrupted verification needs inspection; do not overwrite it')
    if {'load.txt', 'probe.txt'}.intersection(names):
        raise ValueError('An execution log already exists: inspect it before any further load')
    ftp.rename(source, temporary)
    try:
        if read_bounded(ftp, temporary, MAX_PRX) != prx:
            raise ValueError('Staged PRX does not match this build')
    finally:
        ftp.rename(temporary, source)


def send_once(host: str, loader: bytes) -> None:
    require_live_enabled()
    with socket.create_connection((host, 9090), timeout=8) as connection:
        connection.sendall(loader)
        connection.shutdown(socket.SHUT_WR)
    # Delivery is NOT execution success, nor confirmation of a visible pet.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'send', 'status'))
    parser.add_argument('--host', required=True)
    parser.add_argument('--build', type=Path, default=Path(__file__).parent / 'build')
    parser.add_argument('--home-menu', action='store_true', help='Console is at home, no game running')
    args = parser.parse_args()
    if args.action in ('stage', 'send'):
        require_live_enabled()  # Stop before connecting even to FTP.
    if args.action == 'send' and not args.home_menu:
        parser.error('Only home-menu tests are implemented; pass --home-menu after checking the console')
    with ftplib.FTP(timeout=8) as ftp:
        ftp.connect(args.host, 2121)
        ftp.login()
        if args.action == 'status':
            for name in ('load.txt', 'probe.txt'):
                try:
                    value = read_bounded(ftp, REMOTE + '/' + name, MAX_LOG)
                except ftplib.error_perm:
                    print(name + ': not available')
                    continue
                print(name + ':\n' + value.decode('utf-8', 'replace'))
            return
        prx = (args.build / 'arfoxia_probe.prx').read_bytes()
        loader = (args.build / 'arfoxia_probe_loader.bin').read_bytes()
        validate(prx, loader)
        if args.action == 'stage':
            print('PRX staged, readback SHA256:', stage(ftp, prx))
        else:
            verify_staged(ftp, prx)
            send_once(args.host, loader)
            print('One loader delivered. Inspect status; this does not confirm a running pet.')


if __name__ == '__main__':
    try:
        main()
    except (EOFError, OSError, ftplib.Error, ValueError) as exc:
        raise SystemExit(f'Probe stopped ({type(exc).__name__}): {exc}. No automatic resend.') from None

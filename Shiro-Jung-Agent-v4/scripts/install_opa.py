"""Install OPA 1.0.1 from official GitHub assets with SHA256 verification."""
from pathlib import Path
import hashlib
import os
import platform
import re
import sys
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.1'

def main():
    system=platform.system().lower();machine=platform.machine().lower()
    arch={'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(machine)
    if arch is None or system not in {'linux','darwin','windows'}:
        raise SystemExit('Unsupported platform; install an officially verified OPA binary and set SUSHI_OPA_BINARY')
    asset=f'opa_{system}_{arch}'+('_static' if system=='linux' else '.exe' if system=='windows' else '')
    destination=ROOT/'tools'/'opa'/('opa.exe' if system=='windows' else 'opa')
    # A bundled, previously verified Linux binary can be checked without downloading again.
    checksum_file=destination.with_name('opa.sha256')
    if system=='linux' and arch=='amd64' and destination.exists() and checksum_file.exists():
        expected=checksum_file.read_text().split()[0]
        if hashlib.sha256(destination.read_bytes()).hexdigest()==expected:
            destination.chmod(0o755);print('Verified existing OPA:',destination);return
    url=f'https://github.com/open-policy-agent/opa/releases/download/v{VERSION}/{asset}'
    with urllib.request.urlopen(url+'.sha256',timeout=30) as r:
        checksum_text=r.read().decode()
    expected=checksum_text.split()[0]
    if not re.fullmatch('[0-9a-fA-F]{64}',expected): raise SystemExit('Invalid official checksum file')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as tmp:
        temporary=Path(tmp.name)
        try:
            with urllib.request.urlopen(url,timeout=60) as response:
                while chunk:=response.read(1024*1024): tmp.write(chunk)
        except Exception:
            temporary.unlink(missing_ok=True);raise
    try:
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:
            raise SystemExit('OPA checksum mismatch; binary was not installed')
        temporary.chmod(0o755);os.replace(temporary,destination)
        checksum_file.write_text(expected+'  '+asset+'\n')
    finally:
        temporary.unlink(missing_ok=True)
    print('Verified and installed OPA',VERSION,system,arch)

if __name__=='__main__': main()

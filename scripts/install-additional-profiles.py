#!/usr/bin/python3
"""Provision two isolated interfaces; abort on existing files or ports."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
from pathlib import Path

ROOT = Path('/etc/amnezia/amneziawg')
PROFILE_ROOT = Path('/etc/awg-cita/profiles')
SYSTEMD = Path('/etc/systemd/system')
AWG = Path('/opt/amneziawg/3.1.20260828/bin')
INTERFACES = {'awg2': 'awg-cita2', 'wg': 'awg-cita-wg'}


def write_new(path: Path, content: str, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def run(*argv: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(argv, input=stdin, capture_output=True, timeout=15,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if result.returncode:
        raise RuntimeError('profile provisioning command failed')
    return result.stdout


def profile_values(name: str) -> dict[str, str]:
    if name == 'wg':
        return {}
    values = {'S1': '20', 'S2': '24', 'S3': '0', 'S4': '0'}
    numbers = secrets.SystemRandom().sample(range(100000000, 2000000000), 4)
    values.update({f'H{index}': str(number) for index, number in enumerate(numbers, 1)})
    return values


def config_text(name: str, interface: str, address: str, port: int, egress: str, private: str,
                obfuscation: dict[str, str]) -> str:
    network = ipaddress.ip_interface(address).network
    comment = 'AWG-CITA-' + name.upper()
    lines = ['[Interface]', f'Address = {address}', f'ListenPort = {port}', f'PrivateKey = {private}',
             'MTU = 1420',
             f'PostUp = iptables -I FORWARD 1 -i %i -s {network} -o {egress} -m comment --comment {comment} -j ACCEPT',
             f'PostUp = iptables -I FORWARD 1 -o %i -d {network} -i {egress} -m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment {comment} -j ACCEPT',
             f'PostUp = iptables -t nat -I POSTROUTING 1 -s {network} -o {egress} -m comment --comment {comment} -j MASQUERADE',
             f'PostDown = iptables -D FORWARD -i %i -s {network} -o {egress} -m comment --comment {comment} -j ACCEPT || true',
             f'PostDown = iptables -D FORWARD -o %i -d {network} -i {egress} -m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment {comment} -j ACCEPT || true',
             f'PostDown = iptables -t nat -D POSTROUTING -s {network} -o {egress} -m comment --comment {comment} -j MASQUERADE || true']
    if name == 'awg2':
        lines.extend(['Jc = 0', 'Jmin = 0', 'Jmax = 0'])
        lines.extend(f'{key} = {value}' for key, value in obfuscation.items())
    return '\n'.join(lines) + '\n'


def unit_text(interface: str) -> str:
    return f'''[Unit]
Description=AWG-CITA isolated interface {interface}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=WG_QUICK_USERSPACE_IMPLEMENTATION={AWG}/amneziawg-go
Environment=PATH={AWG}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStartPre=/bin/sh -ec 'test ! -d /sys/module/amneziawg; ! /sbin/modprobe -n amneziawg >/dev/null 2>&1'
ExecStart={AWG}/awg-quick up {interface}
ExecStop={AWG}/awg-quick down {interface}

[Install]
WantedBy=multi-user.target
'''


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit('root required')
    parser = argparse.ArgumentParser(description='Provision isolated AWG-CITA profiles')
    parser.add_argument('--endpoint-host', required=True)
    parser.add_argument('--egress-interface', required=True)
    parser.add_argument('--dns-server', required=True)
    for name in INTERFACES:
        parser.add_argument('--' + name + '-address', required=True)
        parser.add_argument('--' + name + '-port', type=int, required=True)
    args = parser.parse_args()
    if (not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', args.endpoint_host) or
        not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', args.egress_interface)):
        parser.error('invalid endpoint or egress interface')
    try:
        dns_server = str(ipaddress.ip_address(args.dns_server))
    except ValueError:
        parser.error('invalid DNS server')
    profiles = {}
    for name, interface in INTERFACES.items():
        address = getattr(args, name + '_address')
        port = getattr(args, name + '_port')
        try:
            parsed = ipaddress.ip_interface(address)
        except ValueError:
            parser.error('invalid profile address')
        if parsed.version != 4 or not 24 <= parsed.network.prefixlen <= 29 or not 1 <= port <= 65535:
            parser.error('invalid profile address or port')
        profiles[name] = (interface, str(parsed), port)
    if (len({value[2] for value in profiles.values()}) != len(profiles) or
        ipaddress.ip_interface(profiles['awg2'][1]).network.overlaps(ipaddress.ip_interface(profiles['wg'][1]).network)):
        parser.error('profile ports and networks must be distinct')
    for binary in (AWG / 'awg', AWG / 'awg-quick', AWG / 'amneziawg-go'):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise SystemExit('pinned AWG userspace stack unavailable')
    targets = []
    route_data = json.loads(run('/usr/sbin/ip', '-j', '-4', 'route', 'show'))
    occupied = [ipaddress.ip_network(row['dst']) for row in route_data
                if isinstance(row.get('dst'), str) and row['dst'] != 'default']
    for name, (interface, address, port) in profiles.items():
        targets.extend((ROOT / (interface + '.conf'), PROFILE_ROOT / (name + '.json'),
                        SYSTEMD / ('awg-cita-' + name + '.service')))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('0.0.0.0', port))
        if any(ipaddress.ip_interface(address).network.overlaps(route) for route in occupied):
            raise SystemExit('profile route overlaps an existing network')
    if any(path.exists() or path.is_symlink() for path in targets):
        raise SystemExit('profile files already exist; refusing overwrite')
    PROFILE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PROFILE_ROOT, 0o700)
    Path('/var/backups/awg-cita-profiles').mkdir(mode=0o700, exist_ok=True)
    for name, (interface, address, port) in profiles.items():
        private = run(str(AWG / 'awg'), 'genkey').decode('ascii').strip()
        obfuscation = profile_values(name)
        config = config_text(name, interface, address, port, args.egress_interface, private, obfuscation)
        settings = json.dumps({'endpoint_host': args.endpoint_host,
                               'dns_server': dns_server,
                               'interface_address': address, 'listen_port': port,
                               'obfuscation': obfuscation}, separators=(',', ':')) + '\n'
        write_new(ROOT / (interface + '.conf'), config, 0o600)
        write_new(PROFILE_ROOT / (name + '.json'), settings, 0o600)
        write_new(SYSTEMD / ('awg-cita-' + name + '.service'), unit_text(interface), 0o644)
    run('/usr/bin/systemctl', 'daemon-reload')
    for name in profiles:
        run('/usr/bin/systemctl', 'enable', '--now', 'awg-cita-' + name + '.service')
        run('/usr/sbin/ufw', 'allow', str(profiles[name][2]) + '/udp', 'comment', 'AWG-CITA ' + name)
    print('isolated profiles active')


if __name__ == '__main__':
    main()

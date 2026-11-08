"""Destructive synthetic bootstrap acceptance: disposable Ubuntu systemd VM only."""
import argparse, base64, hashlib, http.client, json, os, secrets, shutil, subprocess, sys, tempfile, time, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build
import install

def run(*a,**kw):return subprocess.run(a,check=True,capture_output=True,text=True,timeout=90,**kw)
def put(p,b,mode=0o600):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);p.chmod(mode)
def stamp(paths):return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def main(work,wheel,deps,official):
    if os.environ.get('AWG_CITA_DISPOSABLE_VM')!='1' or os.geteuid()!=0:raise RuntimeError('explicit disposable root VM required')
    if Path('/opt/awg-cita').exists() or Path('/etc/awg-cita').exists():raise RuntimeError('requires clean host; existing deployment will not be touched')
    assert Path('/proc/1/comm').read_text().strip()=='systemd'
    # GitHub runner images make /opt runner-writable. A clean production host must
    # have a root-owned, non-writable code ancestor; establish that only in this VM.
    for ancestor in ['/opt','/usr/local','/usr/local/bin','/usr/local/sbin']:
        os.chown(ancestor,0,0);os.chmod(ancestor,0o755)
    work.mkdir(parents=True,exist_ok=True)
    # Genuine artifact check is deliberately separate from the fixture-backed panel.
    assert hashlib.sha256(official.read_bytes()).hexdigest()==build.LOCK['awg']['artifact_sha256']
    with zipfile.ZipFile(official) as z:b=z.read(build.LOCK['awg']['binary_path_in_zip'])
    assert hashlib.sha256(b).hexdigest()==build.LOCK['awg']['binary_sha256']
    real=work/'genuine-awg';put(real,b,0o755)
    assert run(str(real),'--version').stdout.strip()=='amneziawg-tools v3.1.20260812 - https://amnezia.org'
    run(str(real),'show','interfaces');print('GENUINE_AWG_READONLY_PASS',flush=True)
    # No tunnel or kernel modules are created. The fixture has no networking side effects.
    key=base64.b64encode(bytes(range(64,96))).decode()
    dump='\t'.join(['fixture','fixture','51820']+['0']*26)+'\n'+'\t'.join([key,'(none)','(none)','127.0.0.2/32','0','0','0','off'])+'\n'
    fixture=Path('/opt/awg-fixture/awg')
    code='#!/usr/bin/python3\nimport sys\na=sys.argv[1:]\nif a==["--version"]:print("amneziawg-tools v3.1.20260812 - https://amnezia.org")\nelif a==["show","interfaces"]:print("awg-canary0 awg-cita2 awg-cita-wg")\nelif len(a)==3 and a[0]=="show" and a[2]=="dump":print('+repr(dump)+',end="")\nelse:raise SystemExit(64)\n'
    put(fixture,code.encode(),0o755)
    fixture.parent.chmod(0o755)
    for d in ['/etc/awg-cita','/etc/awg-cita/profiles','/etc/awg-cita/client-templates','/etc/amnezia/amneziawg']:
        Path(d).mkdir(parents=True,mode=0o700,exist_ok=True);Path(d).chmod(0o700)
    obf={x:'0' for x in ['S1','S2','S3','S4','H1','H2','H3','H4']}
    profile=dict(public_key=key,route='127.0.0.2/32',endpoint_host='panel.example.test',dns_server='127.0.0.1',obfuscation=obf,interface_address='127.0.0.1/24',listen_port=51820)
    put('/etc/awg-cita/protected-peer.json',json.dumps(profile).encode())
    config=('[Interface]\nPrivateKey = fixture-only\nListenPort = 51820\n\n[Peer]\nPublicKey = '+key+'\nAllowedIPs = 127.0.0.2/32\n').encode()
    vpn=[]
    for name in ['awg-canary0','awg-cita2','awg-cita-wg']:
        p=Path('/etc/amnezia/amneziawg')/(name+'.conf');put(p,config);vpn.append(p)
    for name in ['awg2','wg']:
        value={k:v for k,v in profile.items() if k not in ['public_key','route']};value['obfuscation']=obf if name=='awg2' else {}
        p=Path('/etc/awg-cita/profiles')/(name+'.json');put(p,json.dumps(value).encode());vpn.append(p)
    vpn.append(Path('/etc/awg-cita/protected-peer.json'));before=stamp(vpn)
    run('groupadd','--system','awg-cita-relay') if subprocess.run(['getent','group','awg-cita-relay'],capture_output=True).returncode else None
    gid=install.grp.getgrnam('awg-cita-relay').gr_gid
    # Credentials and Caddy are prerequisites, not installer-owned files.
    c=dict(build.validate({**json.loads((build.HERE/'host.example.json').read_text()),'awg_binary':str(fixture),'awg_sha256':install.sha(fixture),'auth_file':'/etc/awg-cita-operator-auth/hash'}))
    cp=work/'host.json';cp.write_text(json.dumps(c))
    bundle=work/'bundle';m=build.build(cp,wheel,deps,bundle)
    site=bundle/'payload'/m['release_path'].lstrip('/')/'site'
    pw=secrets.token_urlsafe(20)
    r=run('/usr/bin/python3','-IB','-c','import sys;sys.path.insert(0,sys.argv[1]);import bcrypt;print(bcrypt.hashpw(sys.argv[2].encode(),bcrypt.gensalt(rounds=4)).decode())',str(site),pw)
    auth=Path(c['auth_file']);put(auth,(r.stdout.strip()+'\n').encode(),0o640);os.chown(auth,0,gid);auth.parent.chmod(0o750);os.chown(auth.parent,0,gid)
    auth_sha=install.sha(auth)
    run('usermod','-aG','awg-cita-relay','caddy')
    # Local HTTP test frontend; app's origin remains HTTPS and is checked explicitly.
    put('/etc/caddy/Caddyfile',b'http://127.0.0.1:18080 {\n reverse_proxy unix//run/awg-cita-relay/relay.sock {\n header_up Host panel.example.test\n header_up -X-AWG-Operator\n }\n}\n',0o644)
    run('systemctl','restart','caddy')
    def unchanged():assert not os.path.lexists(install.CURRENT) and stamp(vpn)==before
    install.preflight(bundle);unchanged();print('PREFLIGHT_PASS',flush=True)
    # Fail-closed mutations are restricted to test bundle bytes; current never changes.
    row=next(r for r in m['files'] if r['destination'].endswith('/site/awg_cita/app.py'))
    p=bundle/row['source'];original=p.read_bytes();p.write_bytes(original+b'\n')
    try:install.preflight(bundle);raise AssertionError('SHA mismatch accepted')
    except ValueError:pass
    p.write_bytes(original);unchanged();print('SHA_GATE_PASS',flush=True)
    fixture.rename(fixture.with_suffix('.missing'))
    try:install.preflight(bundle);raise AssertionError('missing dependency accepted')
    except ValueError:pass
    fixture.with_suffix('.missing').rename(fixture);unchanged();print('DEPENDENCY_GATE_PASS',flush=True)
    manifest_path=bundle/'manifest.json';manifest_raw=manifest_path.read_bytes()
    def bad_payload_gate(suffix,new,label):
        r=next(r for r in m['files'] if r['destination'].endswith(suffix));p=bundle/r['source'];old=p.read_bytes();old_sha=r['sha256'];old_len=r['bytes']
        p.write_bytes(new);r.update(sha256=hashlib.sha256(new).hexdigest(),bytes=len(new));manifest_path.write_text(json.dumps(m))
        try:
            try:install.preflight(bundle);raise AssertionError(label+' accepted')
            except (ValueError,subprocess.CalledProcessError):pass
        finally:p.write_bytes(old);r.update(sha256=old_sha,bytes=old_len);manifest_path.write_bytes(manifest_raw)
        unchanged();print(label+'_PASS',flush=True)
    bad_payload_gate('/site/awg_cita/app.py',b'raise RuntimeError("synthetic import failure")\n','IMPORT_GATE')
    # Missing supplied helper bytes are a package-integrity failure before current.
    helper=next(r for r in m['files'] if r['destination']=='/usr/local/sbin/awg-cita-peer');hp=bundle/helper['source'];hraw=hp.read_bytes();hp.unlink()
    try:
        try:install.preflight(bundle);raise AssertionError('missing helper accepted')
        except ValueError:pass
    finally:hp.write_bytes(hraw)
    unchanged();print('HELPER_GATE_PASS',flush=True)
    bad_payload_gate('/etc/systemd/system/awg-cita.service',b'[Service]\nExecStart=/missing-fixture-executable\n','UNIT_GATE')
    # An unsafe pre-existing socket object must fail before the initial switch.
    sp=Path('/run/awg-cita-app/backend.sock');sp.parent.mkdir(parents=True,exist_ok=True);put(sp,b'wrong object',0o666)
    try:
        try:install.preflight(bundle);raise AssertionError('socket permission accepted')
        except ValueError:pass
    finally:sp.unlink();sp.parent.rmdir()
    unchanged();print('SOCKET_PERMISSION_GATE_PASS',flush=True)
    saved_switch=install.switch
    def fail_switch(_):raise RuntimeError('synthetic failure before current switch')
    install.switch=fail_switch
    try:
        try:install.install(bundle);raise AssertionError('switch fault ignored')
        except RuntimeError:pass
    finally:install.switch=saved_switch
    unchanged();assert all(not Path('/etc/systemd/system/'+u+'.service').exists() for u in install.UNITS)
    print('PRE_SWITCH_ROLLBACK_PASS',flush=True)
    # Full service-account install, real bcrypt login, and authenticated API through Caddy.
    install.install(bundle)
    def api(path,method='GET',body=None,cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1',18080,timeout=30)
        headers={'Host':'127.0.0.1:18080','Origin':c['origin'],'Sec-Fetch-Site':'same-origin'}
        if body is not None:body=json.dumps(body);headers['Content-Type']='application/json'
        if cookie:headers['Cookie']=cookie
        conn.request(method,path,body=body,headers=headers);r=conn.getresponse();b=r.read();h=dict(r.getheaders());s=r.status;conn.close();return s,h,b
    def login_checks():
        assert api('/api/actions')[0]==401
        s,h,_=api('/auth/login','POST',{'username':c['operator_id'],'password':pw});assert s==200,s
        auth_cookie=h['Set-Cookie'].split(';',1)[0]
        s,h,_=api('/',cookie=auth_cookie);assert s==200,s
        backend_cookie=h['Set-Cookie'].split(';',1)[0]
        cookie=auth_cookie+'; '+backend_cookie
        s,_,b=api('/api/actions',cookie=cookie);assert s==200,(s,b[:100])
        data=json.loads(b);assert len(data['events'])<=200 and type(data['truncated'])==bool and b'nonce_digest' not in b
        for name in ['awg3','awg2','wg']:
            s,_,b=api('/api/profiles/'+name+'/clients',cookie=cookie);assert s==200,(name,s,b[:120]);assert len(json.loads(b)['clients'])==1
        assert stamp(vpn)==before
    login_checks();print('SERVICE_ACCOUNT_CADDY_LOGIN_PROFILES_AUDIT_PASS',flush=True)
    assert run('runuser','-u','caddy','--','test','-w','/run/awg-cita-relay/relay.sock').returncode==0
    # Extra arguments cannot turn the fixed read helper into a privileged shell.
    r=subprocess.run(['runuser','-u','awg-manager','--','sudo','-n','/usr/local/sbin/awg-manager-read','unexpected'],capture_output=True)
    assert r.returncode!=0
    install.install(bundle);login_checks();print('IDEMPOTENT_INSTALL_PASS',flush=True)
    run('systemctl','restart',*install.UNITS)
    for _ in range(60):
        if Path('/run/awg-cita-relay/relay.sock').exists():break
        time.sleep(.5)
    install.verify(m);login_checks();print('RUNTIME_SOCKET_RECREATION_PASS',flush=True)
    # New host configuration is a new release; rollback returns old running services.
    c2=dict(c,origin='https://panel.example.test:9444');cp.write_text(json.dumps(c2));second=work/'bundle-update';m2=build.build(cp,wheel,deps,second)
    old=install.CURRENT.resolve();install.install(second);assert install.CURRENT.resolve()!=old
    tx=sorted(install.STATE.iterdir(),key=lambda p:p.stat().st_mtime_ns)[-1]
    logs=list(Path('/var/lib/awg-cita-audit').glob('*.jsonl'));logdata={p:p.read_bytes() for p in logs}
    install.rollback(tx);assert install.CURRENT.resolve()==old;install.verify(m);login_checks()
    assert all(p.read_bytes().startswith(b) for p,b in logdata.items());print('UPGRADE_ROLLBACK_PASS',flush=True)
    # Roll back the original clean-host transaction: no imaginary old service start.
    first=sorted(install.STATE.iterdir(),key=lambda p:p.stat().st_mtime_ns)[0]
    install.rollback(first)
    assert not os.path.lexists(install.CURRENT)
    assert all(not Path('/etc/systemd/system/'+u+'.service').exists() for u in install.UNITS)
    assert stamp(vpn)==before and all(p.exists() for p in logs) and install.sha(auth)==auth_sha
    print('CLEAN_HOST_ROLLBACK_LOGS_VPN_PRESERVED_PASS',flush=True)
    marker=json.loads((bundle/'payload'/m['release_path'].lstrip('/')/'RELEASE_MARKER').read_text())
    (work/'result.json').write_text(json.dumps(dict(result='PASS',systemd=True,fixture_awg=True,genuine_awg_readonly=True,application_commit=build.LOCK['application_commit'],deployment_commit=marker['deployment_commit']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--wheel',type=Path,required=True);p.add_argument('--dependencies',type=Path,required=True);p.add_argument('--official-awg',type=Path,required=True);a=p.parse_args();main(a.work,a.wheel,a.dependencies,a.official_awg)

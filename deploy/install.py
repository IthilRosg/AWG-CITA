"""Panel-only transactional installer. Never manages VPN, credentials, or Caddy reload."""
import argparse, base64, grp, hashlib, http.client, json, os, platform, pwd, re
import shutil, socket, stat, subprocess, sys, tempfile, time
from pathlib import Path

UNITS=('awg-cita','awg-cita-rate-limit')
PAIRS=(UNITS,('awg-cita-app','awg-cita-relay'))
CURRENT=Path('/opt/awg-cita/current')
STATE=Path('/var/backups/awg-cita-deployment')
FIXED={
 '/etc/systemd/system/awg-cita.service','/etc/systemd/system/awg-cita-rate-limit.service',
 '/etc/systemd/system/awg-cita-app.service','/etc/systemd/system/awg-cita-relay.service',
 '/etc/systemd/system/caddy.service.d/awg-cita-relay.conf',
 '/usr/local/bin/awg-cita-read','/usr/local/sbin/awg-manager-read',
 '/usr/local/sbin/awg-cita-peer','/usr/local/sbin/awg-cita-profile','/usr/local/sbin/awg-cita-template',
 '/etc/sudoers.d/awg-manager','/etc/sudoers.d/awg-cita-canary',
 '/etc/sudoers.d/awg-cita-profiles','/etc/sudoers.d/awg-cita-templates',
}

def run(*args, check=True, **kw):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=60,**kw)

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def units(m):
    result=(m['host']['units']['backend'],m['host']['units']['relay'])
    if result not in PAIRS:raise ValueError('unsupported unit mapping')
    return result

def safe_parents(p):
    for q in [p,*p.parents]:
        if q == Path('/'):continue
        if q.is_symlink():raise ValueError('symlink component: '+str(q))
        if q.exists():
            s=q.stat()
            if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('writable/untrusted component: '+str(q))

def directories(path):
    if path.exists():return
    directories(path.parent)
    path.mkdir(mode=0o755)
    os.chmod(path,0o755)
    os.chown(path,0,0)

def atomic(path,raw,mode=0o644,uid=0,gid=0):
    directories(path.parent)
    fd,n=tempfile.mkstemp(prefix='.awg-cita-',dir=path.parent)
    try:
        os.fchmod(fd,mode);os.fchown(fd,uid,gid)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(n,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.lexists(n):os.unlink(n)

def save(tx,s):atomic(tx/'state.json',(json.dumps(s,sort_keys=True,indent=2)+'\n').encode(),0o600)

def load(bundle):
    bundle=bundle.resolve();m=json.loads((bundle/'manifest.json').read_text())
    if m['schema']!=1 or not re.fullmatch(r'd8d5257-runtime-20261106-deploy-[a-f0-9]{12}',m['release']):raise ValueError('manifest schema/release')
    if m['release_path']!='/opt/awg-cita/releases/'+m['release']:raise ValueError('release path')
    # Hashes must describe actual supplied bytes, not normalized source text.
    seen=set()
    for r in m['files']:
        dest=r['destination'];src=bundle/r['source']
        if dest not in FIXED and not dest.startswith(m['release_path']+'/'):raise ValueError('out of scope destination')
        if '..' in Path(dest).parts or '..' in Path(r['source']).parts or Path(r['source']).is_absolute():raise ValueError('unsafe path')
        if dest in seen or r['owner']!='root' or r['group']!='root' or r['mode'] not in (0o644,0o755,0o440):raise ValueError('invalid file metadata')
        seen.add(dest)
        if src.is_symlink() or not src.is_file() or src.stat().st_size!=r['bytes'] or sha(src)!=r['sha256']:raise ValueError('SHA mismatch: '+dest)
    actual={str(p.relative_to(bundle)) for p in (bundle/'payload').rglob('*') if p.is_file()}
    if actual!={r['source'] for r in m['files']}:raise ValueError('extra/missing payload file')
    return m

def request(path,host,socket_path='/run/awg-cita-app/backend.sock',cookie=None):
    c=http.client.HTTPConnection('localhost',timeout=30)
    c.sock=socket.socket(socket.AF_UNIX);c.sock.settimeout(30);c.sock.connect(socket_path)
    h={'Host':host,'X-AWG-Operator':request.operator,'Connection':'close'}
    if cookie:h['Cookie']=cookie
    c.request('GET',path,headers=h);r=c.getresponse();b=r.read();headers=dict(r.getheaders());status=r.status;c.close()
    return status,headers,b

def preflight(bundle):
    if os.geteuid()!=0:raise PermissionError('root required')
    m=load(bundle);c=m['host']
    if platform.machine()!='x86_64' or sys.version_info[:2]!=(3,12):raise ValueError('requires Ubuntu amd64 Python 3.12')
    osrelease=Path('/etc/os-release').read_text()
    if 'ID=ubuntu' not in osrelease or 'VERSION_ID="24.04"' not in osrelease:raise ValueError('requires Ubuntu 24.04')
    if Path('/proc/1/comm').read_text().strip()!='systemd':raise ValueError('systemd PID1 required')
    for cmd in ('/usr/bin/sudo','/usr/sbin/visudo','/usr/bin/systemctl','/usr/bin/systemd-analyze','/usr/bin/caddy'):
        if not os.access(cmd,os.X_OK):raise ValueError('missing host dependency: '+cmd)
    awg=Path(c['awg_binary']);safe_parents(awg)
    if not awg.is_file() or sha(awg)!=c['awg_sha256']:raise ValueError('host AWG SHA mismatch')
    if run(str(awg),'--version').stdout.strip()!=c['awg_version']:raise ValueError('host AWG version mismatch')
    run(str(awg),'show','interfaces')
    for r in m['files']:
        p=Path(r['destination']);safe_parents(p)
        if p.exists() and not p.is_file():raise ValueError('destination conflict')
        if p.is_file() and p.is_relative_to(m['release_path']) and sha(p)!=r['sha256']:raise ValueError('immutable release conflict')
    for u in units(m):
        if list(Path('/etc/systemd/system/'+u+'.service.d').glob('*.conf')):raise ValueError('existing service drop-ins require separate reconciliation')
    if os.path.lexists(CURRENT) and not CURRENT.is_symlink():raise ValueError('current must be a symlink')
    link=Path('/usr/local/bin/awg')
    if os.path.lexists(link) and link.resolve()!=awg.resolve():raise ValueError('existing AWG link conflict')
    # Never create/overwrite credentials or profiles. Check host-local ownership.
    auth=Path(c['auth_file']);s=auth.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=0o640:raise ValueError('unsafe auth file')
    if s.st_gid!=grp.getgrnam('awg-cita-relay').gr_gid:raise ValueError('auth group mismatch')
    for p in ['/etc/awg-cita/protected-peer.json',c['config_root']+'/awg-canary0.conf']:
        s=Path(p).lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid or s.st_mode&0o077:raise ValueError('unsafe existing profile prerequisite')
    for folder in ('/etc/awg-cita/client-templates',c['profile_root']):
        if not Path(folder).is_dir():raise ValueError('missing host profile prerequisite')
    # Existing Caddy process must already have relay group; no Caddy restart is performed.
    pid=run('systemctl','show','caddy','-p','MainPID','--value').stdout.strip()
    status=Path('/proc/'+pid+'/status').read_text()
    gids=[int(x) for x in re.search(r'^Groups:\s*(.*)$',status,re.M)[1].split()]
    if grp.getgrnam('awg-cita-relay').gr_gid not in gids:raise ValueError('running Caddy lacks relay group; separate restart/configuration needed')
    for name,mode in [('app',0o600),('relay',0o660)]:
        p=Path('/run/awg-cita-'+name)/('backend.sock' if name=='app' else 'relay.sock')
        if p.parent.exists():
            d=p.parent.lstat();expected=0o700 if name=='app' else 0o750
            if not stat.S_ISDIR(d.st_mode) or stat.S_IMODE(d.st_mode)!=expected or d.st_uid!=pwd.getpwnam('awg-manager').pw_uid:raise ValueError('unsafe existing socket directory')
        if os.path.lexists(p) and not p.is_symlink():
            s=p.lstat()
            if not stat.S_ISSOCK(s.st_mode) or stat.S_IMODE(s.st_mode)!=mode or s.st_uid!=pwd.getpwnam('awg-manager').pw_uid:raise ValueError('unsafe existing socket')
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                try:probe.connect(str(p))
                except ConnectionRefusedError:pass
                else:
                    unit=units(m)[0 if name=='app' else 1]
                    if run('systemctl','is-active',unit,check=False).stdout.strip()!='active':raise ValueError('socket listener not managed by expected service')
    site=bundle/'payload'/m['release_path'].lstrip('/')/'site'
    code='import sys;sys.path.insert(0,sys.argv[1]);import awg_cita.cli,awg_cita.profile_helper,awg_cita.canary_helper,segno,bcrypt;assert segno.make_qr("fixture").png_data_uri().startswith("data:image/png;base64,");assert bcrypt.checkpw(b"fixture",bcrypt.hashpw(b"fixture",bcrypt.gensalt(rounds=4)))'
    run('/usr/bin/python3','-IB','-c',code,str(site))
    for r in m['files']:
        p=bundle/r['source']
        if r['destination'].startswith('/etc/sudoers.d/'):
            run('/usr/sbin/visudo','-cf',str(p))
        if r['destination'].endswith('.service'):
            run('/usr/bin/systemd-analyze','verify',str(p))
    return m

def snapshot(p):
    if not os.path.lexists(p):return {'kind':'missing'}
    s=p.lstat()
    r=dict(uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))
    if stat.S_ISLNK(s.st_mode):return dict(r,kind='link',target=os.readlink(p))
    if not stat.S_ISREG(s.st_mode):raise ValueError('cannot snapshot non-file '+str(p))
    return dict(r,kind='file',data=base64.b64encode(p.read_bytes()).decode())

def restore(p,r):
    if r['kind']=='file':atomic(p,base64.b64decode(r['data']),r['mode'],r['uid'],r['gid']);return
    if os.path.lexists(p):p.unlink()
    if r['kind']=='link':p.symlink_to(r['target']);os.lchown(p,r['uid'],r['gid'])

def switch(target):
    q=CURRENT.with_name('.current-awg-cita-next')
    if os.path.lexists(q):raise ValueError('unfinished symlink transaction')
    q.symlink_to(target);os.replace(q,CURRENT)

def wait_sockets():
    for _ in range(100):
        if all(Path(p).exists() for p in ('/run/awg-cita-app/backend.sock','/run/awg-cita-relay/relay.sock')):return
        time.sleep(.2)
    raise TimeoutError('backend/relay socket readiness timeout')

def rollback(tx):
    s=json.loads((tx/'state.json').read_text())
    old_units=tuple(s['units'])
    if set(old_units) not in [set(p) for p in PAIRS]:raise ValueError('rollback unit scope')
    for u in reversed(old_units):run('systemctl','disable','--now',u,check=False)
    for p,r in s['files'].items():restore(Path(p),r)
    for path,r in s.get('runtime_directories',{}).items():
        p=Path(path);p.mkdir(parents=True,exist_ok=True);os.chown(p,r['uid'],r['gid']);os.chmod(p,r['mode'])
    for path,backup in s.get('stale_sockets',{}).items():
        if Path(backup).exists():os.replace(backup,path)
    restore(CURRENT,s['current'])
    run('systemctl','daemon-reload')
    for u,old in s['units'].items():
        if old['enabled'] in ('enabled','enabled-runtime'):run('systemctl','enable',u)
        if old['active']=='active':run('systemctl','start',u)
    if all(old['active']=='active' for old in s['units'].values()):wait_sockets()
    s['rolled_back']=True;save(tx,s)
    print('ROLLBACK_OK audit data and releases retained')

def verify(m):
    for r in m['files']:
        p=Path(r['destination']);s=p.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid or s.st_gid or stat.S_IMODE(s.st_mode)!=r['mode'] or sha(p)!=r['sha256']:raise ValueError('installed manifest drift: '+str(p))
    for u in units(m):
        if run('systemctl','is-active',u).stdout.strip()!='active':raise ValueError('service inactive')
        if run('systemctl','is-enabled',u).stdout.strip()!='enabled':raise ValueError('service not enabled')
    uid=pwd.getpwnam('awg-manager').pw_uid
    for name,mode,gid in [('app',0o600,pwd.getpwnam('awg-manager').pw_gid),('relay',0o660,grp.getgrnam('awg-cita-relay').gr_gid)]:
        p=Path('/run/awg-cita-'+name)/('backend.sock' if name=='app' else 'relay.sock');s=p.lstat()
        if not stat.S_ISSOCK(s.st_mode) or s.st_uid!=uid or s.st_gid!=gid or stat.S_IMODE(s.st_mode)!=mode:raise ValueError('unsafe socket')
    request.operator=m['host']['operator_id'];host=m['host']['host']
    status,h,b=request('/',host)
    if status!=200:raise ValueError('backend root failed')
    cookie=h['Set-Cookie'].split(';',1)[0]
    status,_,b=request('/api/actions',host,cookie=cookie)
    if status!=200:raise ValueError('audit API failed')
    v=json.loads(b)
    if len(v['events'])>200 or type(v['truncated'])!=bool:raise ValueError('audit contract')
    if any(x in b for x in (b'nonce_digest',b'PrivateKey',b'PresharedKey',b'Endpoint =',b'AllowedIPs =')):raise ValueError('unsafe audit projection')
    # Rights are exercised as the service account, not from the installer root session.
    run('/usr/sbin/runuser','-u','awg-manager','--','/usr/local/bin/awg-cita-read','show','awg-canary0','dump')
    run('/usr/sbin/runuser','-u','awg-manager','--','/usr/bin/sudo','-n','/usr/local/sbin/awg-cita-peer','list')
    print('VERIFY_OK')

def install(bundle):
    m=preflight(bundle)
    base=Path(m['release_path']);tx=STATE/(m['release']+'-'+str(time.time_ns()))
    tx.mkdir(parents=True,mode=0o700);os.chmod(STATE,0o700)
    targets=[Path(r['destination']) for r in m['files'] if not Path(r['destination']).is_relative_to(base)]
    targets += [Path('/usr/local/bin/awg')]
    runtime={}
    for name in ('app','relay'):
        p=Path('/run/awg-cita-'+name)
        if p.exists():
            st=p.lstat();runtime[str(p)]=dict(uid=st.st_uid,gid=st.st_gid,mode=stat.S_IMODE(st.st_mode))
    s=dict(current=snapshot(CURRENT),files={str(p):snapshot(p) for p in targets},units={u:dict(active=run('systemctl','is-active',u,check=False).stdout.strip(),enabled=run('systemctl','is-enabled',u,check=False).stdout.strip()) for u in units(m)},created_accounts=[],created_directories=[],runtime_directories=runtime,stale_sockets={})
    save(tx,s);print('TRANSACTION',tx,flush=True)
    try:
        try:pwd.getpwnam('awg-manager')
        except KeyError:
            run('useradd','--system','--user-group','--no-create-home','--shell','/usr/sbin/nologin','awg-manager');s['created_accounts'].append('awg-manager');save(tx,s)
        for r in m['files']:
            p=Path(r['destination'])
            if p.is_file() and sha(p)==r['sha256'] and stat.S_IMODE(p.stat().st_mode)==r['mode'] and p.stat().st_uid==0 and p.stat().st_gid==0:continue
            atomic(p,(bundle/r['source']).read_bytes(),r['mode'])
        link=Path('/usr/local/bin/awg')
        if not os.path.lexists(link):link.symlink_to(m['host']['awg_binary'])
        manager=pwd.getpwnam('awg-manager')
        for name in (str(Path(m['host']['action_audit']).parent),):
            p=Path(name)
            if not p.exists():p.mkdir(mode=0o700,parents=True);os.chown(p,manager.pw_uid,manager.pw_gid);s['created_directories'].append(name);save(tx,s)
            info=p.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=manager.pw_uid or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('unsafe audit directory')
        for u in reversed(units(m)):run('systemctl','stop',u,check=False)
        # Preserve pre-existing dangling links for rollback, never copy live sockets.
        for p in (Path('/run/awg-cita-app/backend.sock'),Path('/run/awg-cita-relay/relay.sock')):
            if p.is_symlink():s['files'][str(p)]=snapshot(p);save(tx,s);p.unlink()
            elif p.exists():
                # Only closed orphan sockets remain after stopping managed services.
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(1)
                    try:probe.connect(str(p))
                    except ConnectionRefusedError:pass
                    else:raise ValueError('refusing to move an active socket')
                backup=Path('/run/awg-cita-deployment-backups')/tx.name/p.name
                directories(backup.parent);os.chmod(backup.parent.parent,0o700)
                s['stale_sockets'][str(p)]=str(backup);save(tx,s);os.replace(p,backup)
        run('systemctl','daemon-reload')
        switch(base)
        for u in units(m):run('systemctl','enable',u);run('systemctl','start',u)
        wait_sockets()
        verify(m);s['completed']=True;save(tx,s)
        print('INSTALL_OK',m['release'])
    except BaseException:
        rollback(tx);raise

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('command',choices=['preflight','install','verify','rollback']);a.add_argument('path',type=Path);x=a.parse_args()
    if x.command=='preflight':preflight(x.path);print('PREFLIGHT_OK')
    elif x.command=='install':install(x.path.resolve())
    elif x.command=='verify':verify(load(x.path.resolve()))
    else:rollback(x.path.resolve())

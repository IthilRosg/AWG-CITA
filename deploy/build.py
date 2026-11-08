"""Assemble exact approved application bytes plus independently versioned deployment."""
import argparse, hashlib, io, json, re, shutil, subprocess, zipfile
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE/'external-lock.json').read_text())
DEPENDENCIES = {
 'segno-1.6.6-py3-none-any.whl': '28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7',
 'bcrypt-4.3.0-cp39-abi3-manylinux_2_28_x86_64.whl': 'f1e3ffa1365e8702dc48c8b360fef8d7afeca482809c5e45e653af82ccd088c1',
}

def validate(c):
    fields = {'host','origin','operator_id','auth_file','awg_binary','awg_sha256','awg_version','interfaces','config_root','profile_root'}
    if set(c) != fields: raise ValueError('host schema mismatch')
    if not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*',c['host']): raise ValueError('invalid host')
    u=urlsplit(c['origin'])
    if u.scheme!='https' or u.hostname!=c['host'] or u.path or u.query or u.fragment or u.username or u.password or u.netloc.endswith(':'): raise ValueError('invalid origin')
    if u.port is not None and not 1<=u.port<=65535: raise ValueError('invalid port')
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',c['operator_id']): raise ValueError('invalid identity')
    for k in ('auth_file','awg_binary'):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',c[k]) or '..' in Path(c[k]).parts: raise ValueError('unsafe path')
    if not re.fullmatch('[a-f0-9]{64}',c['awg_sha256']): raise ValueError('unverified AWG SHA')
    if c['awg_version']!='amneziawg-tools v3.1.20260812 - https://amnezia.org': raise ValueError('unsupported AWG version')
    if c['interfaces']!={'awg3':'awg-canary0','awg2':'awg-cita2','wg':'awg-cita-wg'} or c['config_root']!='/etc/amnezia/amneziawg' or c['profile_root']!='/etc/awg-cita/profiles': raise ValueError('immutable application does not support this profile mapping')
    return c

def digest(raw): return hashlib.sha256(raw).hexdigest()

def build(config, wheel, dependencies, out):
    c=validate(json.loads(config.read_text()))
    raw=wheel.read_bytes()
    if len(raw)!=LOCK['application_wheel_bytes'] or digest(raw)!=LOCK['application_wheel_sha256']: raise ValueError('application artifact mismatch')
    if out.exists(): raise FileExistsError('output must be new')
    depbytes={}
    for name,sha in DEPENDENCIES.items():
        b=(dependencies/name).read_bytes()
        if digest(b)!=sha: raise ValueError('dependency artifact mismatch')
        depbytes[name]=b
    out.mkdir(parents=True)
    payload=out/'payload'; payload.mkdir()
    revision=b''.join(p.read_bytes() for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    release='d8d5257-runtime-20261106-deploy-'+digest(json.dumps(c,sort_keys=True).encode()+revision)[:12]
    base='/opt/awg-cita/releases/'+release
    rows=[]
    def add(dest,b,mode=0o644,section='application runtime'):
        if any(r['destination']==dest for r in rows): raise ValueError('duplicate destination')
        source=dest.lstrip('/'); p=payload/source;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        rows.append(dict(source='payload/'+source,destination=dest,bytes=len(b),sha256=digest(b),owner='root',group='root',mode=mode,section=section))
    for name,b in {wheel.name:raw,**depbytes}.items():
        add(base+'/wheels/'+name,b,section='external artifacts' if name in depbytes else 'application runtime')
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            for info in z.infolist():
                n=Path(info.filename)
                if n.is_absolute() or '..' in n.parts or (info.external_attr>>16)&0o170000==0o120000: raise ValueError('unsafe wheel')
                if info.is_dir():continue
                add(base+'/site/'+info.filename,z.read(info),section='external dependencies' if name in depbytes else 'application runtime')
    for name in ('rate_limit_proxy.py','operator_auth.py'):
        # Approved runtime files were built from CRLF Git source. Verify actual bytes.
        b=subprocess.check_output(['git','show',LOCK['application_commit']+':scripts/'+name],cwd=HERE.parent).replace(b'\n',b'\r\n')
        add(base+'/'+name,b)
    add(base+'/DEPLOYMENT_HOST.json',(json.dumps(c,sort_keys=True,indent=2)+'\n').encode(),section='host-specific prerequisites')
    marker={'application_commit':LOCK['application_commit'],'application_wheel_sha256':LOCK['application_wheel_sha256'],'deployment_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE.parent,text=True).strip(),'release':release}
    add(base+'/RELEASE_MARKER',(json.dumps(marker,sort_keys=True)+'\n').encode())
    replacements={'HOST':c['host'],'ORIGIN':c['origin'],'OPERATOR_ID':c['operator_id'],'AUTH_FILE':c['auth_file'],'AWG_BINARY':c['awg_binary']}
    for name,dest,mode,section in [
      ('awg-cita.service','/etc/systemd/system/awg-cita.service',0o644,'systemd deployment'),
      ('awg-cita-rate-limit.service','/etc/systemd/system/awg-cita-rate-limit.service',0o644,'systemd deployment'),
      ('awg-cita-read','/usr/local/bin/awg-cita-read',0o755,'privileged helper runtime'),
      ('awg-manager-read','/usr/local/sbin/awg-manager-read',0o755,'privileged helper runtime'),
      ('awg-manager.sudoers','/etc/sudoers.d/awg-manager',0o440,'privileged helper runtime'),
      ('caddy-group.conf','/etc/systemd/system/caddy.service.d/awg-cita-relay.conf',0o644,'systemd deployment')]:
        s=(HERE/'templates'/name).read_text()
        for key,value in replacements.items():s=s.replace('@'+key+'@',value)
        add(dest,s.encode(),mode,section)
    for name in ('awg-cita-peer','awg-cita-profile','awg-cita-template','awg-cita-canary.sudoers','awg-cita-profiles.sudoers','awg-cita-templates.sudoers'):
        dest='/etc/sudoers.d/'+name.removesuffix('.sudoers') if name.endswith('.sudoers') else '/usr/local/sbin/'+name
        add(dest,subprocess.check_output(['git','show',LOCK['application_commit']+':scripts/'+name],cwd=HERE.parent),0o440 if name.endswith('.sudoers') else 0o755,'privileged helper runtime')
    manifest=dict(schema=1,release=release,release_path=base,host=c,artifacts=LOCK,files=sorted(rows,key=lambda r:r['destination']),excluded=['VPN configurations','clients','credentials','audit logs','.ops-tmp','kernel modules','network rules'])
    (out/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    shutil.copyfile(HERE/'install.py',out/'install.py')
    (out/'SHA256SUMS').write_text(''.join(digest((out/n).read_bytes())+'  '+n+'\n' for n in ('manifest.json','install.py')))
    return manifest

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--config',type=Path,required=True);a.add_argument('--wheel',type=Path,required=True);a.add_argument('--dependencies',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    args=a.parse_args();m=build(args.config,args.wheel,args.dependencies,args.out);print(json.dumps({'release':m['release'],'files':len(m['files'])}))

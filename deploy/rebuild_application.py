"""Reproduce the previously approved Windows-built application artifact on Linux."""
import base64, csv, hashlib, io, json, os, subprocess, sys, tarfile, tempfile, zipfile
from pathlib import Path
lock=json.loads((Path(__file__).parent/'external-lock.json').read_text())
out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    raw=subprocess.check_output(['git','archive',lock['application_commit']])
    root=Path(tmp)
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:t.extractall(root,filter='data')
    for p in root.rglob('*'):
        if p.is_file():
            b=p.read_bytes()
            if b'\0' not in b:p.write_bytes(b.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
    env=dict(os.environ,SOURCE_DATE_EPOCH=str(lock['source_date_epoch']))
    subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation','--wheel-dir',str(out),str(root)],env=env,check=True)
p=out/'awg_cita-0.2.0-py3-none-any.whl'
# Reproduce Windows ZIP origin/attributes and generated metadata line endings.
# These are part of the approved artifact bytes, not application code changes.
with zipfile.ZipFile(p) as z:
    items=[(i,z.read(i)) for i in z.infolist()]
converted={i.filename:(b.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n') if i.filename.endswith('/METADATA') else b) for i,b in items}
record='awg_cita-0.2.0.dist-info/RECORD'
s=io.StringIO();writer=csv.writer(s,lineterminator='\n')
for i,_ in items:
    b=converted[i.filename]
    writer.writerow([i.filename,'',''] if i.filename==record else [i.filename,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(b).digest()).decode().rstrip('='),len(b)])
converted[record]=s.getvalue().encode()
with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for i,_ in items:
        i.create_system=0;i.external_attr=2176057344 if i.filename==record else 2176188416
        z.writestr(i,converted[i.filename])
assert p.stat().st_size==lock['application_wheel_bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==lock['application_wheel_sha256'],'approved application artifact drift'
print('APPROVED_WHEEL_REPRODUCED')

from http.server import BaseHTTPRequestHandler
from http.client import HTTPConnection
from socketserver import ThreadingMixIn
try:
 from socketserver import UnixStreamServer
except ImportError:
 UnixStreamServer = object  # type: ignore[assignment,misc]  # Windows can compile; execution fails closed below.
from urllib.parse import urlsplit
from contextlib import closing
import os
import re
import socket
import stat
import threading,time
HOST=os.environ.get("AWG_CITA_OPERATOR_HOST") or "panel.example"
ORIGIN=os.environ.get("AWG_CITA_OPERATOR_ORIGIN") or "https://panel.example:8444"
OPERATOR_ID=os.environ.get("AWG_CITA_OPERATOR_ID") or "test-operator"
BACKEND_SOCKET="/run/awg-cita-app/backend.sock"; RELAY_SOCKET="/run/awg-cita-relay/relay.sock"; lock=threading.Lock(); tokens=6.0; last=time.monotonic()
action_lock=threading.Lock(); action_tokens=6.0; action_last=time.monotonic(); action_slots=threading.BoundedSemaphore(3)
client_lock=threading.Lock(); client_tokens=6.0; client_last=time.monotonic()
ACTION_BACKEND_TIMEOUT=330  # Longer than the app's bounded helper operation and rollback.
CLIENT_READ_TIMEOUT=30  # Longer than the app's bounded list helper and lock wait.

class UnixHTTPConnection(HTTPConnection):
 def __init__(self,path,timeout):
  super().__init__("localhost",timeout=timeout)
  self.socket_path=path
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
  try:
   self.sock.settimeout(self.timeout)
   self.sock.connect(self.socket_path)
  except BaseException:
   self.sock.close()
   raise

class RelayServer(ThreadingMixIn,UnixStreamServer):
 daemon_threads=True
 def __init__(self,path,handler,*,owner_uid,group_gid):
  parent=os.lstat(os.path.dirname(path))
  if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=owner_uid or parent.st_mode & 0o022:
   raise PermissionError("unsafe relay socket directory")
  try:
   os.lstat(path)
  except FileNotFoundError:
   pass
  else:
   raise FileExistsError("relay socket path already exists")
  self.owner_uid=owner_uid
  self.group_gid=group_gid
  self.bound_inode=None
  old_umask=os.umask(0o177)
  try:
   super().__init__(path,handler)
  finally:
   os.umask(old_umask)
 def server_bind(self):
  super().server_bind()
  try:
   created=os.lstat(self.server_address)
   if not stat.S_ISSOCK(created.st_mode) or created.st_uid!=self.owner_uid:
    raise PermissionError("unsafe relay socket identity")
   self.bound_inode=(created.st_dev,created.st_ino)
   os.chown(self.server_address,self.owner_uid,self.group_gid)
   os.chmod(self.server_address,0o660)
   entry=os.lstat(self.server_address)
   if (not stat.S_ISSOCK(entry.st_mode) or (entry.st_dev,entry.st_ino)!=self.bound_inode or
       (entry.st_uid,entry.st_gid,stat.S_IMODE(entry.st_mode))!=(self.owner_uid,self.group_gid,0o660)):
    raise PermissionError("unsafe relay socket permissions")
  except BaseException:
   self.socket.close()
   self._unlink_own_socket()
   raise
 def _unlink_own_socket(self):
  if self.bound_inode is None:return
  try:
   entry=os.lstat(self.server_address)
  except FileNotFoundError:
   return
  if stat.S_ISSOCK(entry.st_mode) and (entry.st_dev,entry.st_ino)==self.bound_inode:
   os.unlink(self.server_address)
  self.bound_inode=None
 def server_close(self):
  super().server_close()
  self._unlink_own_socket()
def permitted():
 global tokens,last
 with lock:
  now=time.monotonic();tokens=min(6.0,tokens+(now-last)*0.5);last=now
  if tokens<1:return False
  tokens-=1;return True
def action_permitted():
 global action_tokens,action_last
 with action_lock:
  now=time.monotonic();action_tokens=min(6.0,action_tokens+(now-action_last)*0.5);action_last=now
  if action_tokens<1:return False
  action_tokens-=1;return True
def client_permitted():
 global client_tokens,client_last
 with client_lock:
  now=time.monotonic();client_tokens=min(6.0,client_tokens+(now-client_last)*0.5);client_last=now
  if client_tokens<1:return False
  client_tokens-=1;return True
class Handler(BaseHTTPRequestHandler):
 protocol_version="HTTP/1.1"
 def log_message(self,*args):pass
 def operator_id(self):
  values=self.headers.get_all("X-AWG-Operator")
  return OPERATOR_ID if values==[OPERATOR_ID] else None
 def session_cookie(self):
  fields=self.headers.get_all("Cookie")
  if fields is None or len(fields)!=1:return None
  values=[part.strip().split("=",1)[1] for part in fields[0].split(";") if part.strip().startswith("awg_cita_session=")]
  if len(values)!=1 or not 1<=len(values[0])<=128:return None
  return "awg_cita_session="+values[0]
 def do_GET(self):
  if self.headers.get_all("Host")!=[HOST]:self.send_error(421);return
  actor=self.operator_id()
  if actor is None:self.send_error(401);return
  path=urlsplit(self.path).path
  if path=="/api/status" and not permitted():self.send_response(429);self.send_header("Content-Length","0");self.end_headers();return
  is_client_read=(path=="/api/clients" or bool(re.fullmatch(r"/api/clients/peer-[0-9a-f]{16}/config",self.path)) or
                   bool(re.fullmatch(r"/api/profiles/(?:awg3|awg2|wg)/(?:clients(?:/peer-[0-9a-f]{16}/config)?|template|server)",self.path)))
  if is_client_read and self.session_cookie() is None:self.send_error(401);return
  if is_client_read and not client_permitted():self.send_error(429);return
  if is_client_read and not action_slots.acquire(blocking=False):self.send_error(429);return
  started=False
  try:
   headers={"Host":HOST,"X-AWG-Operator":actor}
   if cookie:=self.session_cookie():headers["Cookie"]=cookie
   with closing(UnixHTTPConnection(BACKEND_SOCKET,timeout=CLIENT_READ_TIMEOUT if is_client_read else 10)) as c:
    c.request("GET",self.path,headers=headers);r=c.getresponse();b=r.read();status=r.status;response_headers=r.getheaders()
   started=True;self.send_response(status)
   for k,v in response_headers:
    if k.lower() not in {"connection","keep-alive","transfer-encoding","content-length"}:self.send_header(k,v)
   self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
  except Exception:
   if started:self.close_connection=True
   else:self.send_error(503)
  finally:
   if is_client_read:action_slots.release()
 def do_POST(self):
  if self.headers.get_all("Host")!=[HOST]:self.send_error(421);return
  actor=self.operator_id()
  if actor is None:self.send_error(401);return
  if (self.path!="/api/clients" and
      not re.fullmatch(r"/api/clients/peer-[0-9a-f]{16}/(?:disable|enable|delete|config)",self.path) and
      not re.fullmatch(r"/api/profiles/(?:awg3|awg2|wg)/(?:clients(?:/peer-[0-9a-f]{16}/(?:disable|enable|delete|config))?|template|server(?:/port)?)",self.path)):
   self.send_error(404);return
  if self.headers.get_all("Origin")!=[ORIGIN]:self.send_error(403);return
  csrf=self.headers.get_all("X-CSRF-Token")
  if csrf is None or len(csrf)!=1 or not csrf[0] or len(csrf[0])>128:self.send_error(403);return
  if self.headers.get("Sec-Fetch-Site","same-origin")!="same-origin":self.send_error(403);return
  if self.headers.get_all("Content-Type")!=["application/json"]:self.send_error(415);return
  lengths=self.headers.get_all("Content-Length")
  if lengths is None or len(lengths)!=1 or not 1<=len(lengths[0])<=4 or not lengths[0].isdigit() or not 1<=int(lengths[0])<=2048 or self.headers.get_all("Transfer-Encoding") is not None:self.send_error(400);return
  cookie=self.session_cookie()
  if cookie is None:self.send_error(401);return
  if not action_permitted():self.send_error(429);return
  if not action_slots.acquire(blocking=False):self.send_error(429);return
  started=False
  try:
   self.connection.settimeout(10)
   body=self.rfile.read(int(lengths[0]))
   if len(body)!=int(lengths[0]):
    self.close_connection=True
    self.send_error(400)
    return
   headers={"Host":HOST,"X-AWG-Operator":actor,"Cookie":cookie,"Origin":ORIGIN,"X-CSRF-Token":csrf[0],"Content-Type":"application/json","Sec-Fetch-Site":"same-origin"}
   with closing(UnixHTTPConnection(BACKEND_SOCKET,timeout=ACTION_BACKEND_TIMEOUT)) as c:
    c.request("POST",self.path,body=body,headers=headers);r=c.getresponse();result=r.read();status=r.status;response_headers=r.getheaders()
   started=True;self.send_response(status)
   for k,v in response_headers:
    if k.lower() not in {"connection","keep-alive","transfer-encoding","content-length"}:self.send_header(k,v)
   self.send_header("Content-Length",str(len(result)));self.end_headers();self.wfile.write(result)
  except Exception:
   if started:self.close_connection=True
   else:self.send_error(503)
  finally:action_slots.release()
if __name__=="__main__":
 if os.name!="posix":raise RuntimeError("Unix sockets require POSIX")
 if not os.environ.get("AWG_CITA_OPERATOR_HOST") or not os.environ.get("AWG_CITA_OPERATOR_ORIGIN") or not os.environ.get("AWG_CITA_OPERATOR_ID"):
  raise RuntimeError("operator host, origin, and identity must be configured")
 parsed=urlsplit(ORIGIN)
 if (parsed.scheme!="https" or parsed.hostname!=HOST or parsed.path or parsed.query or parsed.fragment or
     parsed.username is not None or parsed.password is not None or not re.fullmatch(r"[a-z0-9.-]{1,253}",HOST) or
     not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}",OPERATOR_ID)):
  raise RuntimeError("invalid operator host or origin")
 import grp
 import pwd
 owner=pwd.getpwnam("awg-manager").pw_uid
 group=grp.getgrnam("awg-cita-relay").gr_gid
 if os.geteuid()!=owner or group not in (os.getegid(),*os.getgroups()):
  raise PermissionError("relay identity or socket group unavailable")
 with RelayServer(RELAY_SOCKET,Handler,owner_uid=owner,group_gid=group) as server:
  server.serve_forever()

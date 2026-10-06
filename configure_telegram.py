"""Pair a dedicated prediction bot with the existing owner. Root terminal only."""
import argparse, getpass, hashlib, json, os, pathlib, pwd, re, secrets, subprocess, tempfile, time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

TARGET=pathlib.Path('/opt/vivameda-prediction-scanner/telegram_credentials.json')
CRYPTO=pathlib.Path('/opt/vivameda-crypto-early-scout/credentials.json')
TIMER='vivameda-prediction-scanner.timer'
SERVICE='vivameda-prediction-scanner.service'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Redirect refused')

def bot_id(token):
    if not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token):
        raise ValueError('Invalid token')
    return int(token.split(':')[0])

def api(token,method,**params):
    if method not in ('getMe','getWebhookInfo','getUpdates','sendMessage'):
        raise ValueError('Unsupported operation')
    req=Request('https://api.telegram.org/bot'+token+'/'+method,
                data=urlencode(params).encode(),method='POST')
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as response:
        raw=response.read(1000001)
    if len(raw)>1000000:raise ValueError('Response too large')
    body=json.loads(raw)
    if body.get('ok') is not True:raise ValueError('Telegram request failed')
    return body['result']

def verify_bot(token,crypto_token,me,webhook):
    if bot_id(token)==bot_id(crypto_token):raise ValueError('Use a different bot from Crypto Lab')
    if me.get('id')!=bot_id(token) or me.get('is_bot') is not True:
        raise ValueError('Bot identity mismatch')
    if not isinstance(me.get('username'),str) or not re.fullmatch(r'[A-Za-z0-9_]{5,32}',me['username']):
        raise ValueError('Invalid bot username')
    if me['username'].lower()=='vivameda_boss_bot':raise ValueError('Manager bot cannot be reused')
    if webhook.get('url'):raise ValueError('Bot already has a webhook; use a new bot')

def paired(updates,owner,challenge,since):
    matches=[]
    for u in updates:
        m=u.get('message',{});chat=m.get('chat',{});sender=m.get('from',{})
        if (m.get('text')=='/start '+challenge and chat.get('type')=='private'
                and str(chat.get('id'))==str(owner) and str(sender.get('id'))==str(owner)
                and sender.get('is_bot') is False and isinstance(m.get('date'),int)
                and m['date']>=since):
            matches.append(chat['id'])
    return bool(matches)

def safe_read(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlink refused')
    return json.loads(path.read_text())

def atomic_write(path,data,gid):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlink refused')
    fd,name=tempfile.mkstemp(prefix='.telegram-',dir=path.parent)
    try:
        os.fchmod(fd,0o640);os.fchown(fd,0,gid)
        with os.fdopen(fd,'w') as f:
            json.dump(data,f);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def command(args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=60)

def switch(data,gid,send_confirmation,command_fn=command):
    """Serialize against the scanner and restore prior destination on failure."""
    previous=safe_read(TARGET)
    active=command_fn(['systemctl','is-active',TIMER]).stdout.strip()=='active'
    command_fn(['systemctl','stop',TIMER])
    try:
        command_fn(['systemctl','stop',SERVICE])
        atomic_write(TARGET,data,gid)
        if send_confirmation() is not True:raise ValueError('Confirmation failed')
    except Exception:
        atomic_write(TARGET,previous,gid)
        raise
    finally:
        if active:command_fn(['systemctl','start',TIMER])

def main():
    p=argparse.ArgumentParser();p.add_argument('--expected-sha256',required=True);a=p.parse_args()
    if hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()!=a.expected_sha256:
        raise SystemExit('Reviewed setup source changed')
    if os.geteuid()!=0:raise SystemExit('Run inside the Hetzner root terminal')
    if not os.isatty(0):raise SystemExit('Interactive terminal required')
    current=safe_read(TARGET);crypto=safe_read(CRYPTO)
    owner=current.get('chat_id')
    if not str(owner).isdigit() or int(owner)<=0:raise ValueError('Existing private owner destination required')
    token=getpass.getpass('NEW prediction-market bot token (hidden): ').strip()
    me=api(token,'getMe')
    verify_bot(token,crypto.get('bot_token'),me,api(token,'getWebhookInfo'))
    # Leave existing updates untouched: only a fresh, unpredictable owner-bound challenge matches.
    since=int(time.time());challenge=secrets.token_urlsafe(24)
    print('Open @'+me['username']+' on your phone and send:')
    print('/start '+challenge)
    input('After sending that exact command, press Enter: ')
    deadline=time.monotonic()+45
    matched=False;offset=None
    while time.monotonic()<deadline and not matched:
        params={'timeout':0,'limit':100,'allowed_updates':json.dumps(['message'])}
        if offset is not None:params['offset']=offset
        updates=api(token,'getUpdates',**params)
        matched=paired(updates,owner,challenge,since)
        if updates:offset=max(u['update_id'] for u in updates)+1
        if not matched:time.sleep(1)
    if not matched:raise ValueError('Owner pairing not found; configuration unchanged')
    candidate={'bot_token':token,'chat_id':int(owner),'purpose':'prediction_markets',
               'bot_id':me['id'],'bot_username':me['username'],'paired_at':int(time.time())}
    gid=pwd.getpwnam('vivameda-agent').pw_gid
    def confirm():
        api(token,'sendMessage',chat_id=owner,text='Vivameda Prediction Markets connected.\nPrediction-market candidate alerts will arrive here with market links.\nCrypto Lab remains in its existing chat. Live betting disabled.')
        return True
    switch(candidate,gid,confirm)
    print(json.dumps({'configured':True,'dedicated_bot':True,'owner_pairing_verified':True,
                      'confirmation_sent':True,'crypto_modified':False,'live_execution':False}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # HTTP exceptions include token URLs; never print their bodies.
        raise SystemExit('Prediction bot setup failed ('+type(exc).__name__+'); no credentials printed. Rerun setup with the exact pairing command.')

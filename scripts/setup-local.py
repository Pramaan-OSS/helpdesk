#!/usr/bin/env python3
"""Create this template's local infrastructure. Existing sites are preserved."""
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / '.runtime' / 'bench'
SITES = BENCH / 'sites'

def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)

def container(name, image, ports, *options):
    exists = subprocess.run(['docker', 'inspect', name], capture_output=True).returncode == 0
    if exists:
        run('docker', 'start', name, stdout=subprocess.DEVNULL)
    else:
        run('docker', 'run', '-d', '--name', name, '-p', ports, *options, image, stdout=subprocess.DEVNULL)

for folder in [SITES, BENCH/'apps', BENCH/'logs', ROOT/'.tools'/'bin']:
    folder.mkdir(parents=True, exist_ok=True)
password_file = BENCH / '.local-db-password'
if not password_file.exists():
    existing = subprocess.run(['docker', 'inspect', 'pramaan-helpdesk-db'], capture_output=True, text=True)
    if existing.returncode == 0:
        variables = json.loads(existing.stdout)[0]['Config']['Env']
        passwords = [value.split('=', 1)[1] for value in variables if value.startswith('MARIADB_ROOT_PASSWORD=')]
        if not passwords:
            raise SystemExit('The existing local database needs its saved root password in .runtime/bench/.local-db-password.')
        password_file.write_text(passwords[0])
    else:
        password_file.write_text(secrets.token_urlsafe(24))
    password_file.chmod(0o600)
db_password = password_file.read_text().strip()
container('pramaan-helpdesk-db', 'mariadb:11.8', '127.0.0.1:13316:3306', '-e', 'MARIADB_ROOT_PASSWORD='+db_password)
container('pramaan-helpdesk-cache', 'redis:7.4.11-alpine', '127.0.0.1:16319:6379')
for target, source in [(BENCH/'env', ROOT/'.venv'), (BENCH/'apps'/'frappe', ROOT/'vendor'/'framework'), (BENCH/'apps'/'helpdesk', ROOT)]:
    if not target.exists():
        target.symlink_to(source, target_is_directory=True)
(SITES/'apps.txt').write_text('frappe\nhelpdesk\n')
(SITES/'common_site_config.json').write_text(json.dumps({
    'db_host':'127.0.0.1','db_port':13316,'use_mysqlclient':0,
    'redis_cache':'redis://127.0.0.1:16319','redis_queue':'redis://127.0.0.1:16319','redis_socketio':'redis://127.0.0.1:16319',
    'socketio_port':19009,'webserver_port':18008,'webserver_host':'127.0.0.1','default_site':'pramaan.localhost','developer_mode':1,'serve_default_site':True,
    'server_script_enabled':0,'enable_telemetry':False,'pause_scheduler':False,'disable_scheduler':False,
}, indent=2))
wrapper = ROOT/'.tools'/'bin'/'mariadb'
wrapper.write_text('''#!/usr/bin/env python3
import os,sys
args=[a.replace("13316", "3306") if a.startswith("--port") else a for a in sys.argv[1:]]
os.execvp("docker",["docker","exec","-i","pramaan-helpdesk-db","mariadb",*args])
''')
wrapper.chmod(0o755)
mysql = wrapper.with_name('mysql')
if not mysql.exists():mysql.symlink_to(wrapper)
env = {**os.environ, 'FRAPPE_PRELOAD_DATABASE_DRIVERS':'none', 'PATH':str(wrapper.parent)+os.pathsep+os.environ['PATH']}
python = str(ROOT/'.venv'/'bin'/'python')
if not (SITES/'pramaan.localhost'/'site_config.json').exists():
    # Wait for this local database to be ready, without contacting any outside API.
    import time
    for _ in range(60):
        check=subprocess.run(['docker','exec','pramaan-helpdesk-db','healthcheck.sh','--connect','--innodb_initialized'],capture_output=True)
        if check.returncode == 0:break
        time.sleep(1)
    else:raise SystemExit('Local database did not become ready.')
    admin_password = secrets.token_urlsafe(20)
    credential_file = BENCH/'.local-admin-password'
    credential_file.write_text(admin_password)
    credential_file.chmod(0o600)
    run(python,'-m','frappe.utils.bench_helper','frappe','new-site','pramaan.localhost','--db-type','mariadb',
        '--db-host','127.0.0.1','--db-port','13316','--db-root-password',db_password,'--admin-password',admin_password,
        '--mariadb-user-host-login-scope','%','--set-default','--install-app','helpdesk',cwd=SITES,env=env)
run(python,'-m','frappe.utils.bench_helper','frappe','--site','pramaan.localhost','enable-scheduler',cwd=SITES,env=env)
site_config = json.loads((SITES/'pramaan.localhost'/'site_config.json').read_text())
if 'helpdesk' not in site_config.get('installed_apps', []):
    run(python,'-m','frappe.utils.bench_helper','frappe','--site','pramaan.localhost','install-app','helpdesk',cwd=SITES,env=env)
assets=SITES/'assets';assets.mkdir(exist_ok=True)
for name, source in [('helpdesk', ROOT/'helpdesk'/'public'),('frappe',ROOT/'vendor'/'framework'/'frappe'/'public')]:
    link=assets/name
    if not link.exists():link.symlink_to(source,target_is_directory=True)
if not (assets/'assets.json').exists():(assets/'assets.json').write_text('{}')
if (BENCH/'.local-admin-password').exists():
    print('Local site prepared. Sign in as Administrator; local password is in .runtime/bench/.local-admin-password.')
else:
    print('Existing local site preserved. Sign in with its current Administrator password.')

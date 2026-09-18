"""Start a dedicated cloud-disabled Ollama daemon; refuse an unknown existing server."""
import os
import shutil
import socket
import subprocess

binary = shutil.which('ollama')
if not binary:
    raise SystemExit('Install Ollama and download the reviewed local model first.')
with socket.socket() as sock:
    sock.settimeout(1)
    if sock.connect_ex(('127.0.0.1', 11434)) == 0:
        raise SystemExit('Port 11434 is already in use. Quit the Ollama tray app/service before starting this dedicated daemon.')
env = dict(os.environ)
env.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_NO_CLOUD='1', OLLAMA_DEBUG='0', OLLAMA_CONTEXT_LENGTH='2048', OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_MAX_QUEUE='1')
# Only a model server; do not give it the app's AWS credentials or shared proxy secrets.
for key in list(env):
    if key.startswith('AWS_') or key.upper() in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','JWT_SECRET','DATA_KEY'}:
        env.pop(key)
print('Starting loopback-only Ollama with cloud features disabled. Keep this terminal open.')
raise SystemExit(subprocess.call([binary, 'serve'], env=env))

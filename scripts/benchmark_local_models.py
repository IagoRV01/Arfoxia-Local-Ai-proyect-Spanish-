"""Opt-in installed-model benchmark; app must be paused with no resident models.

Uses only an owned loopback server on port 11437 and synthetic inputs. Never
downloads models, writes chats, changes saved settings or stops other servers.
Run from the project root; private logs/results are stored in ignored work/.
"""
import argparse
import base64
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import re

import httpx
import psutil
from glaceon_companion.config import ConfigStore
from glaceon_companion.dual_gpu import DualGpuRuntime
from glaceon_companion.model_policy import probe_nvidia_gpus, detect_game_processes

parser = argparse.ArgumentParser()
parser.add_argument('--profile', choices=['normal', 'large', 'power', 'gaming', 'dual'], default='dual')
parser.add_argument('--variant', default='baseline')
parser.add_argument('--batch', type=int, choices=[32, 64, 128, 256, 512], default=128)
parser.add_argument('--draft', type=int, choices=range(0, 5), default=1)
parser.add_argument('--split', choices=['86,14', '80,20', '75,25'], default='75,25')
parser.add_argument('--samples', type=int, default=2)
parser.add_argument('--tokens', type=int, default=128)
parser.add_argument('--long', action='store_true')
parser.add_argument('--prompt-paragraphs', type=int, default=220)
parser.add_argument('--think', choices=['off', 'high'], default='off')
parser.add_argument('--vision', action='store_true')
parser.add_argument('--temperature', type=float, default=0)
args = parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', args.variant):
    parser.error('--variant must be an alphanumeric report label')
if not 1 <= args.samples <= 5 or not 32 <= args.tokens <= 1024 or not 0 <= args.temperature <= 2:
    parser.error('samples must be 1..5, tokens 32..1024, temperature 0..2')
if not 1 <= args.prompt_paragraphs <= 500:
    parser.error('prompt-paragraphs must be 1..500')

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

store = ConfigStore()
config = store.load()
runtime = DualGpuRuntime(config, None)
base = 'http://127.0.0.1:11437'
client = httpx.Client(timeout=httpx.Timeout(900, connect=3), trust_env=False)
reply = client.get(f'http://127.0.0.1:{config.api_port}/api/model/status',
                   headers={'Authorization': 'Bearer ' + store.api_token()})
reply.raise_for_status()
status = reply.json()
require(status.get('ai_paused') is True and not status.get('switching_to'), 'Preserve active app session')
tasks_path = store.data_dir / 'work-tasks.json'
records = json.loads(tasks_path.read_text()) if tasks_path.exists() else {}
require(not any(row.get('status') in {'queued', 'running', 'cancelling'} for row in records.values()), 'Active work')
game = detect_game_processes(config.game_processes)
require(not game.active and not game.error, 'Game running or unavailable check')
for port in (11434, 11435, 11436):
    try:
        r = client.get(f'http://127.0.0.1:{port}/api/ps')
        require(r.status_code == 200 and not r.json().get('models'), f'Resident model on {port}; preserve it')
    except httpx.ConnectError:
        pass
with socket.socket() as port_check:
    port_check.bind(('127.0.0.1', 11437))
snapshot = probe_nvidia_gpus()
env = runtime.environment(snapshot)
env['OLLAMA_HOST'] = base
env['LLAMA_ARG_TENSOR_SPLIT'] = args.split
if args.profile in ('normal', 'large', 'power'):
    env['CUDA_VISIBLE_DEVICES'] = config.ai_gpu_uuid
    env['OLLAMA_SCHED_SPREAD'] = 'false'
    env.pop('LLAMA_ARG_TENSOR_SPLIT', None)
elif args.profile == 'gaming':
    env['CUDA_VISIBLE_DEVICES'] = config.gaming_gpu_uuid
    env['OLLAMA_SCHED_SPREAD'] = 'false'
    env.pop('LLAMA_ARG_TENSOR_SPLIT', None)
models = {'normal': config.model, 'large': config.large_model, 'power': config.power_model,
          'gaming': config.gaming_gpu_model, 'dual': config.dual_model}
contexts = {'normal': config.context_tokens, 'large': config.large_context_tokens,
            'power': config.power_context_tokens, 'gaming': config.gaming_gpu_context_tokens,
            'dual': runtime.context_tokens}
model = models[args.profile]
known = client.get('http://127.0.0.1:11434/api/tags').json().get('models', [])
require(model in [m['name'] for m in known], 'Installed models only')
owner = next(psutil.Process(c.pid) for c in psutil.net_connections(kind='tcp')
             if c.laddr and c.laddr.port == 11434 and c.status == psutil.CONN_LISTEN)
executable = owner.exe()
require(owner.name().casefold() == 'ollama.exe' and owner.cmdline()[1:] == ['serve'], 'Unverified primary server')
Path('work').mkdir(exist_ok=True)
log_path = Path('work') / f'tuning-{args.profile}-{args.variant}.log'
result_path = log_path.with_suffix('.json')
options = {'num_ctx': contexts[args.profile], 'num_gpu': 999, 'num_batch': args.batch,
           'draft_num_predict': args.draft, 'num_predict': args.tokens, 'temperature': args.temperature, 'seed': 42}
if args.profile in ('power', 'gaming'):
    options['main_gpu'] = 0
prompt = 'Explain how a compiler transforms source code into an executable, with many concrete steps and examples. Write at least 800 words.'
if args.long:
    prompt = ('Reference data for a fictional compiler: lexing parses symbols, parsing creates syntax trees, '
              'type checking verifies expressions, optimization simplifies constant operations, '
              'code generation writes assembly, linking resolves library references.\n' * args.prompt_paragraphs) + '\n' + prompt
result = {'profile': args.profile, 'variant': args.variant, 'model': model, 'options': options,
          'split': env.get('LLAMA_ARG_TENSOR_SPLIT'), 'think': args.think,
          'vision': args.vision, 'prompt_paragraphs': args.prompt_paragraphs if args.long else 0,
          'samples': []}
process = None
try:
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([executable, 'serve'], env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(120):
            require(process.poll() is None, 'Temporary Ollama stopped')
            try:
                r = client.get(base + '/api/version')
                r.raise_for_status()
                result['version'] = r.json()['version']
                require(any(c.pid == process.pid and c.laddr and c.laddr.port == 11437
                            and c.status == psutil.CONN_LISTEN
                            for c in psutil.net_connections(kind='tcp')), 'Temporary server identity mismatch')
                break
            except httpx.HTTPError:
                time.sleep(.25)
        else:
            raise RuntimeError('Temporary server did not start')
        for i in range(args.samples + 1):
            request = {'model': model, 'prompt': prompt, 'think': False, 'stream': False,
                       'keep_alive': -1, 'options': options}
            request['think'] = 'high' if args.think == 'high' else False
            if args.vision:
                from glaceon_companion.config import PROJECT_ROOT
                request['images'] = [base64.b64encode((PROJECT_ROOT / 'mobile/assets/arfoxia.png').read_bytes()).decode()]
                request['prompt'] = 'Describe the character in this image, its colors and its shape, in detail.'
            started = time.monotonic()
            print(json.dumps({'starting_sample': i, 'profile': args.profile, 'variant': args.variant}), flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, base + '/api/generate', json=request)
                while not future.done():
                    concurrent.futures.wait([future], timeout=20)
                    snap = probe_nvidia_gpus()
                    warning = runtime.budget_error(snap)
                    print(json.dumps({'elapsed_s': round(time.monotonic()-started, 1),
                        'vram_mib': {d.index: d.effective_used_vram_mib for d in snap.devices},
                        'warning': warning}), flush=True)
                    # Explicit test teardown, not production residency policy.
                    if warning:
                        DualGpuRuntime._terminate_tree(psutil.Process(process.pid))
                        raise RuntimeError(warning)
                r = future.result()
            r.raise_for_status()
            data = r.json()
            ps = client.get(base + '/api/ps').json().get('models', [])
            loaded = next(m for m in ps if m['name'] == model)
            require(loaded['size_vram'] >= loaded['size'] * .995, 'CPU layers forbidden')
            require(not any('--no-mmproj-offload' in p.cmdline()
                            for p in psutil.Process(process.pid).children(recursive=True)), 'CPU vision projector forbidden')
            sample = {k: data.get(k) for k in ('eval_count', 'eval_duration', 'prompt_eval_count',
                                             'prompt_eval_duration', 'load_duration', 'total_duration')}
            sample['decode_tps'] = round(data.get('eval_count', 0) / max(1, data.get('eval_duration', 0)) * 1e9, 3)
            sample['wall_s'] = round(time.monotonic()-started, 3)
            sample['thinking_chars'] = len(data.get('thinking', ''))
            sample['context_length'] = loaded.get('context_length')
            sample['full_gpu'] = True
            result['samples'].append(sample)
            result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(sample), flush=True)
except Exception as exc:
    result['error'] = str(exc)[:1000]
    result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    raise
finally:
    if process is not None and process.poll() is None:
        owned = psutil.Process(process.pid)
        require(os.path.normcase(owned.exe()) == os.path.normcase(executable), 'Temporary process identity mismatch')
        require(owned.environ().get('OLLAMA_HOST') == base, 'Temporary process environment mismatch')
        DualGpuRuntime._terminate_tree(owned)
    client.close()

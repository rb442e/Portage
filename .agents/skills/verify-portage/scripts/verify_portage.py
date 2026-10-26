#!/usr/bin/env python3
"""Drive isolated Portage instances and preserve verifiable runtime evidence."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SCRIPTS = Path(__file__).resolve().parent
CANDIDATE_ROOT = SCRIPTS.parents[3]
DEFAULT_ROOT = CANDIDATE_ROOT if (CANDIDATE_ROOT / 'backend/app/main.py').exists() else Path.cwd()


class Blocked(RuntimeError):
    """A prerequisite or external service is unavailable; this is not a pass."""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(base, path, method='GET', payload=None, timeout=45):
    req = urllib.request.Request(base + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def environment(root, data):
    # Do not inherit live Jira/Rally credentials, external servers, or product overrides.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('PORTAGE_') and key not in ('JIRA_API_TOKEN', 'RALLY_API_KEY')}
    env.update(PORTAGE_DATA_DIR=str(data), PYTHONPATH=str(root / 'backend'),
               PORTAGE_AUTH_DISABLED='1', PORTAGE_ALLOW_MCP_SERVER_EDITING='1')
    return env


def doctor(root):
    python = root / 'backend/.venv/bin/python'
    if not python.is_file():
        raise Blocked('Missing backend/.venv/bin/python; install backend/requirements.txt in that environment.')
    with tempfile.TemporaryDirectory(prefix='portage-doctor-') as scratch:
        result = subprocess.run([str(python), '-c',
            'import anyio,mcp,uvicorn,cryptography; from app.main import app; print("backend imports ready")'],
            cwd=root, env=environment(root, Path(scratch)),
            text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise Blocked('Backend dependency/import check failed: ' + result.stderr[-1800:])
    return {'backend_python': str(python), 'backend_imports': 'ready',
            'playwright': 'installed' if importlib.util.find_spec('playwright') else 'missing',
            'frontend_builder': (root / 'frontend/node_modules/vite/bin/vite.js').is_file()}


@contextmanager
def instance(root, work, browser=False):
    env = environment(root, work / 'data')
    python = str(root / 'backend/.venv/bin/python')
    processes, logs = [], []
    port, fixture_port = free_port(), free_port()
    while fixture_port == port:
        fixture_port = free_port()
    base = f'http://127.0.0.1:{port}'
    fixture = f'http://127.0.0.1:{fixture_port}/mcp'
    try:
        if browser:
            builder = root / 'frontend/node_modules/vite/bin/vite.js'
            if not builder.is_file():
                raise Blocked('Install frontend dependencies before running browser verification.')
            build_log = work / 'frontend-build.log'
            node = ['node']
            if sys.platform == 'darwin':
                rollup = root / 'frontend/node_modules/@rollup'
                installed = [arch for arch in ('arm64', 'x64') if (rollup / ('rollup-darwin-' + arch)).is_dir()]
                if len(installed) == 1:
                    node = ['/usr/bin/arch', '-' + ('x86_64' if installed[0] == 'x64' else 'arm64'), 'node']
            with build_log.open('w') as stream:
                result = subprocess.run([*node, str(builder), 'build', '--outDir', str(work / 'frontend')],
                    cwd=root / 'frontend', env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            if result.returncode:
                raise Blocked('Frontend build failed; see frontend-build.log')
            env['PORTAGE_FRONTEND_DIST'] = str(work / 'frontend')
        commands = [
            ('fixture.log', [python, str(SCRIPTS / 'fixture_server.py'), '--port', str(fixture_port)]),
            ('backend.log', [python, '-m', 'uvicorn', 'app.main:app', '--app-dir', str(root / 'backend'),
                             '--host', '127.0.0.1', '--port', str(port)]),
        ]
        for name, command in commands:
            stream = (work / name).open('w'); logs.append(stream)
            processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT))
        for _ in range(100):
            if any(process.poll() is not None for process in processes):
                raise Blocked('A verification process exited during startup; see backend.log and fixture.log')
            try:
                request(base, '/api/health', timeout=1)
                with socket.create_connection(('127.0.0.1', fixture_port), timeout=1):
                    break
            except (OSError, ValueError):
                time.sleep(0.1)
        else:
            raise Blocked('Isolated instances did not become ready within 10 seconds')
        yield base, fixture, env
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        for stream in logs:
            stream.close()
        (work / 'cleanup.json').write_text(json.dumps({
            'owned_processes_stopped': all(p.poll() is not None for p in processes),
            'pids': [p.pid for p in processes], 'evidence_preserved': True}, indent=2))


def mcp_check(root, work):
    result = subprocess.run([str(root / 'backend/.venv/bin/python'), str(SCRIPTS / 'probe_mcp.py')],
        cwd=root, env=environment(root, work / 'data'), capture_output=True, text=True, timeout=30)
    (work / 'stdio-stderr.log').write_text(result.stderr)
    require(result.returncode == 0, 'Portage stdio handshake/read failed; see stdio-stderr.log')
    evidence = json.loads(result.stdout)
    (work / 'stdio-result.json').write_text(json.dumps(evidence, indent=2))
    return {'tool_count': len(evidence['tools']), 'read_call': 'list_mappings', 'workspace': 'isolated and empty'}


def browser_context(base, work):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise Blocked('Playwright missing. Run this driver using a Python environment with playwright installed.') from exc
    return sync_playwright()


def tool_access_check(root, work):
    with instance(root, work, browser=True) as (base, fixture, env):
        with browser_context(base, work) as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise Blocked('Chromium unavailable; install Playwright Chromium. ' + str(exc)[:300]) from exc
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
            page = context.new_page(); page.set_default_timeout(15000)
            try:
                page.goto(base)
                page.get_by_role('link', name='Settings', exact=True).click()
                page.get_by_role('button', name='MCP server', exact=True).click()
                page.get_by_role('button', name='Add server', exact=True).click()
                page.get_by_label('Transport', exact=True).select_option('http')
                page.get_by_label('Name', exact=True).fill('verification_fixture')
                page.get_by_label('Remote MCP URL', exact=True).fill(fixture)
                page.screenshot(path=str(work / '01-draft.png'))
                page.get_by_role('button', name='Test connection', exact=True).click()
                page.get_by_text('Connected.', exact=True).wait_for(timeout=30000)
                page.screenshot(path=str(work / '02-discovered.png'))
                page.get_by_role('button', name='Add server', exact=True).last.click()
                card = page.locator('.mcp-card').filter(has_text='verification_fixture')
                card.get_by_text('Connected', exact=True).wait_for(timeout=30000)
                probe = request(base, '/api/settings/mcp/servers/verification_fixture/test', 'POST')
                require(set(probe['tools']) == {'lookup', 'failing_fetch'}, 'Read-only discovery mismatch')
                require(any(tool['name'] == 'write_blocked' for tool in probe['blocked']), 'Write tool was not blocked')
                card.get_by_role('button', name='Lookup', exact=False).click()
                card.get_by_text('Return the verification query unchanged.').wait_for()
                page.screenshot(path=str(work / '03-details.png'))
                card.get_by_role('checkbox', name='Disable Lookup for Sora').click()
                card.get_by_role('checkbox', name='Enable Lookup for Sora').wait_for()
                page.reload()
                page.get_by_role('button', name='MCP server', exact=True).click()
                card = page.locator('.mcp-card').filter(has_text='verification_fixture')
                require(not card.get_by_role('checkbox', name='Enable Lookup for Sora').is_checked(), 'Disabled state did not persist')
                require(card.get_by_role('checkbox', name='Disable Failing Fetch for Sora').is_checked(), 'Other tool unexpectedly disabled')
                card.scroll_into_view_if_needed()
                page.screenshot(path=str(work / '04-disabled-after-reload.png'))
                disabled = request(base, '/api/settings/mcp/servers')['disabled_tools']
                require('ext_verification_fixture__lookup' in disabled, 'Disabled tool not saved')
                card.get_by_role('checkbox', name='Enable Lookup for Sora').click()
                page.get_by_text('lookup enabled for Sora.', exact=True).wait_for()
                require(request(base, '/api/settings/mcp/servers')['disabled_tools'] == [], 'Enable did not persist')
                card.get_by_role('checkbox', name='Available to Sora').click()
                page.wait_for_function("async () => !(await (await fetch('/api/settings/mcp/servers')).json()).enabled_for_sora.includes('verification_fixture')")
                page.screenshot(path=str(work / '05-server-disabled.png'))
                (work / 'remote-discovery.json').write_text(json.dumps(probe, indent=2))
                return {'transport': 'real local Streamable HTTP fixture',
                        'verified': ['draft test completes', 'saved server discovery', 'read-only policy',
                                     'description expansion', 'individual toggle persists after reload',
                                     'other tool remains enabled', 're-enable', 'server availability toggle'],
                        'not_covered': ['Sora model tool selection; use run sora-web and run failed-fetch']}
            finally:
                page.screenshot(path=str(work / 'last-screen.png'))
                context.tracing.stop(path=str(work / 'browser-trace.zip'))
                context.close(); browser.close()


def chat(base, prompt, work, name):
    req = urllib.request.Request(base + '/api/copilot/chat',
        data=json.dumps({'message': prompt, 'page': {'route': '/settings'}}).encode(),
        headers={'Content-Type': 'application/json'})
    events = []
    with urllib.request.urlopen(req, timeout=240) as response:
        for line in response:
            if line.startswith(b'data: '):
                events.append(json.loads(line[6:]))
    (work / f'{name}-events.json').write_text(json.dumps(events, indent=2))
    return events


def sora_check(root, work, model, ollama, failure=False):
    try:
        request(ollama, '/api/tags', timeout=3)
    except (OSError, ValueError) as exc:
        raise Blocked('Ollama is unavailable at ' + ollama) from exc
    with instance(root, work) as (base, fixture, env):
        request(base, '/api/settings/sora', 'PUT', {'values': {'base_url': ollama, 'model': model}})
        if failure:
            request(base, '/api/settings/mcp/servers', 'POST', {
                'name': 'verification_fixture', 'transport': 'http', 'url': fixture, 'enable_for_sora': True})
            events = chat(base, 'Use the failing_fetch tool to retrieve https://example.com and summarize its content. If retrieval fails, explain the failure.', work, 'failed-fetch')
            results = [e for e in events if e['type'] == 'tool_result' and e['name'] == 'ext_verification_fixture__failing_fetch']
            require(results and all(not e['ok'] for e in results), 'Expected the intentional failing fetch to execute and fail')
            answer = ''.join(e['text'] for e in events if e['type'] == 'token')
            require(answer.strip(), 'Sora returned no failure explanation')
            # Output text alone cannot reliably prove absence of unsupported claims.
            return {'tool_failure_observed': True, 'answer': answer,
                    'review_required': 'Inspect failed-fetch-events.json: confirm Sora explains failure and does not claim page contents.'}
        request(base, '/api/settings/mcp/servers', 'POST', {'name': 'parallel_search_mcp', 'transport': 'http',
            'url': 'https://search.parallel.ai/mcp', 'enable_for_sora': True})
        probe = request(base, '/api/settings/mcp/servers/parallel_search_mcp/test', 'POST')
        (work / 'parallel-discovery.json').write_text(json.dumps(probe, indent=2))
        if probe['status'] != 'available':
            raise Blocked('Parallel MCP unavailable; inspect parallel-discovery.json')
        prompts = [
            ('web_search', 'Search the web using Parallel for the official Model Context Protocol documentation. Return the URL and one sentence.'),
            ('web_fetch', 'Use Parallel Web Fetch to fetch https://modelcontextprotocol.org/docs/getting-started/intro and summarize the retrieved page in two sentences.'),
        ]
        for tool, prompt in prompts:
            events = chat(base, prompt, work, tool)
            expected = 'ext_parallel_search_mcp__' + tool
            require(any(e['type'] == 'tool_result' and e['name'] == expected and e['ok'] for e in events), 'No successful ' + expected + '; inspect saved events')
        request(base, '/api/settings/mcp/servers/tool-access', 'PUT',
                {'disabled_tools': ['ext_parallel_search_mcp__web_search']})
        events = chat(base, 'Search the web for Model Context Protocol.', work, 'disabled-search')
        require(not any(e['type'] == 'tool_call' and e.get('name') == 'ext_parallel_search_mcp__web_search' for e in events),
                'Sora attempted to invoke disabled Web Search')
        request(base, '/api/settings/mcp/servers/tool-access', 'PUT', {'disabled_tools': []})
        return {'provider': 'live Parallel MCP', 'model': model,
                'verified': ['successful web_search through Sora', 'successful web_fetch through Sora', 'disabled Web Search not called on the next turn'],
                'not_covered': ['Independent factual accuracy of generated answers']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT, help='Portage checkout root')
    parser.add_argument('--output', type=Path, help='New evidence directory; must not already exist')
    parser.add_argument('--model', default='llama3.1:8b', help='Ollama model for explicit live checks')
    parser.add_argument('--ollama', default='http://127.0.0.1:11434', help='Ollama URL for live checks')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check backend imports and optional browser prerequisites')
    run = sub.add_parser('run', help='Execute isolated checks and preserve evidence')
    run.add_argument('group', choices=['mcp', 'tool-access', 'local', 'sora-web', 'failed-fetch'])
    args = parser.parse_args()
    root = args.root.resolve()
    work = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='portage-verification-'))
    if args.output:
        work.mkdir(parents=True, exist_ok=False)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'root': str(root),
              'evidence': str(work), 'checks': [], 'status': 'passed'}
    try:
        report['prerequisites'] = doctor(root)
        if args.command == 'run':
            checks = ['mcp', 'tool-access'] if args.group == 'local' else [args.group]
            for group in checks:
                case = work / group; case.mkdir()
                start = time.monotonic()
                try:
                    if group == 'mcp': result = mcp_check(root, case)
                    elif group == 'tool-access': result = tool_access_check(root, case)
                    else: result = sora_check(root, case, args.model, args.ollama, failure=group == 'failed-fetch')
                    status = 'review_required' if 'review_required' in result else 'passed'
                    report['checks'].append({'group': group, 'status': status, 'seconds': round(time.monotonic()-start, 2), 'result': result})
                    if status == 'review_required': report['status'] = status
                except Exception as exc:
                    status = 'blocked' if isinstance(exc, Blocked) else 'failed'
                    report['checks'].append({'group': group, 'status': status, 'error': str(exc)})
                    report['status'] = status
                    break
    except Exception as exc:
        report.update(status='blocked' if isinstance(exc, Blocked) else 'failed', error=str(exc))
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    (work / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return {'passed': 0, 'failed': 1, 'blocked': 2, 'review_required': 3}[report['status']]


if __name__ == '__main__':
    sys.exit(main())

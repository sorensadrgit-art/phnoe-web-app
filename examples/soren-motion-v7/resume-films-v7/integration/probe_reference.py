import json
import pathlib
import re
import subprocess

SESSION = 'jesper-motion-01a18094'
BIN = r'C:\Users\soren\AppData\Roaming\npm\node_modules\agent-browser\bin\agent-browser-win32-x64.exe'
OUT = pathlib.Path(__file__).parent / 'jesper-motion-reference'
OUT.mkdir(parents=True, exist_ok=True)

def evaluate(js, session=SESSION):
    result = subprocess.run([BIN, '--session', session, 'eval', '--stdin', '--json'], input=js, text=True, encoding='utf-8', capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    data = json.loads(result.stdout)
    if not data.get('success', True):
        raise RuntimeError(data)
    value = data.get('data', {}).get('result', data)
    return json.loads(value) if isinstance(value, str) else value

if __name__ == '__main__':
    assets = evaluate('JSON.stringify([...new Set(performance.getEntriesByType("resource").filter(e=>e.name.includes("/_nuxt/")&&e.name.endsWith(".js")&&!e.name.includes("basis_transcoder")).map(e=>e.name))])')
    for url in assets:
        source = evaluate('(async()=>JSON.stringify(await (await fetch(' + json.dumps(url) + ')).text()))()')
        name = url.rsplit('/', 1)[-1]
        (OUT / name).write_text(source, encoding='utf-8')
        print(name, len(source), 'bytes')

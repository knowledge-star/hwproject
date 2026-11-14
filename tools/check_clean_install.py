"""Build a clean temporary venv, install only the wheel, run from another cwd.
Uses uv's normal dependency cache/index; no model calls or research data.
"""
from pathlib import Path
import ast
import json
import shutil
import subprocess
import tempfile
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    wheel=next((root/'dist').glob('*.whl'))
    with tempfile.TemporaryDirectory(prefix='skillopt-clean-') as temp:
        directory=Path(temp)
        subprocess.run(['uv','venv','--python',sys.executable,str(directory/'venv')],check=True,capture_output=True)
        python=directory/'venv/bin/python'
        if sys.platform=='win32':python=directory/'venv/Scripts/python.exe'
        subprocess.run(['uv','pip','install','--python',str(python),str(wheel)],check=True,capture_output=True)
        shutil.copytree(root/'configs',directory/'configs')
        shutil.copytree(root/'examples',directory/'examples')
        proof=subprocess.run([str(python),'-I','-c',
           'import json,skill_optimizer; from importlib.metadata import version; '
           'assert "site-packages" in skill_optimizer.__file__; '
           'print(json.dumps({"version":skill_optimizer.__version__,"json_repair":version("json-repair"),"wheel_import":True}))'],
           cwd=directory,check=True,capture_output=True,text=True)
        result=json.loads(proof.stdout)
        for config,label in [('mock.json','synthetic_runtime'),('script.json','script_synthetic_runtime')]:
            subprocess.run([str(python),'-I','-m','skill_optimizer','run','--config',str(directory/'configs'/config),
                            '--output',str(directory/label)],cwd=directory,check=True,capture_output=True,text=True)
            selection=json.loads((directory/label/'selection.json').read_text())
            assert selection['winner']=='round-001'
            result[label+'_closed_loop']=True
        result.update(no_research_sys_path=True,model_calls=0)
    for source in (root/'src').rglob('*.py'):
        ast.parse(source.read_text(encoding='utf-8'),feature_version=(3,10))
    result['python310_syntax_check']=True
    result['python_runtime_tested']=sys.version.split()[0]
    (root/'reports/clean-install.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()

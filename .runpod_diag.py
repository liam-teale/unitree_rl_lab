import os
import socket
import subprocess

print("diag-ok")
print("host", socket.gethostname())
print("cwd", os.getcwd())
subprocess.run(["/bin/bash", "-lc", "whoami; pwd; command -v sshd || true; ps -ef | head -20; ss -ltnp || true"], check=False)

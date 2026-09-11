"""Launch the production Review session using its explicit persistent config."""
import json
import os
from pathlib import Path
import subprocess
import sys

from review_session import ReviewSession


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    if config.get('deployment_mode') != 'production' or config.get('smb_cache_disabled') is not True:
        raise ValueError('Explicit production configuration with cache-disabled SMB required')
    mount = config['required_mount']
    if not os.path.ismount(mount):
        Path(mount).mkdir(parents=True, exist_ok=True)
        subprocess.run(['mount_smbfs', '-N', '-s', '-o', 'nobrowse,nodatacache,nomdatacache',
                        config['smb_share'], mount], check=True)
    ReviewSession(config).run()


if __name__ == '__main__':
    main()

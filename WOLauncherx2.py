#!/usr/bin/env python3

import argparse
import logging
import stat
import urllib.request
import urllib.parse
import json
from pathlib import Path, PurePosixPath
import sys
import os
import configparser
import platform
import datetime
import shutil
import hashlib
from functools import lru_cache
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

# Set up logging configuration
logger = logging.getLogger('WO_Launcherx2')
ch = logging.StreamHandler()
f = logging.Formatter('%(message)s')
logger.addHandler(ch)
CHUNK_SIZE = 1048576  # 1MiB
WURM_MANIFEST_URL = "http://client.wurmonline.com/manifest.php"

# XDG Base Directory Specification for storing configuration, downloads, runtime files, and other data
XDG_CONFIG_HOME = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share"))

LAUNCHER_ROOT = XDG_DATA_HOME / "WO_Launcherx2"
LAUNCHER_DOWNLOADS = LAUNCHER_ROOT / "downloads"
LAUNCHER_RUNTIME = LAUNCHER_ROOT / "runtime"
LAUNCHER_CLIENTS = LAUNCHER_ROOT / "clients"
LAUNCHER_WORK = LAUNCHER_ROOT / "work"
LAUNCHER_CONFIG_FILE = XDG_CONFIG_HOME / "WO_Launcherx2" / "config.ini"

# Default configuration settings for the launcher
LAUNCHER_CONFIG_DEFAULT = {
    'DEFAULT': {
        'Debug': 'False'
    },
    'LAUNCH-DEFAULT': {
        'Name': 'Default',
        'Options': '-XX:+UseG1GC -XX:MaxGCPauseMillis=8 '
                   '-XX:MinHeapFreeRatio=11 -XX:MaxHeapFreeRatio=18'
    },
    'LAUNCH-LOWMEM': {
        'Name': 'Low Memory',
        'Options': '-Xmx1G -Xms128M'
    },
    'LAUNCH-LOWLATENCY': {
        'Name': "Low Latency",
        'Options': '-XX:+UseShenandoahGC -Xmx4G -Xms256M'
    },
    'CLIENT': {
        'Name': 'Live'
    },
    'JDK': {
        'Version': '17',
        'Type': 'ga'
    },
    'JFX': {
        'Version': '17.0.13'
    },
    'JCEF': {}
}

# Calculates the SHA-256 checksum for a given file to verify file integrity
def sha256sum(file: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file.absolute(), 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()

# Defines a generic Dependency class that handles downloading and extracting dependencies
class Dependency:
    def __init__(self, url: str = None, file_name: str = None, path: Path = None, *args, **kwargs):
        self.url = url
        self.file_name = file_name
        self._download_path = None
        self._path = path

    def is_ready(self) -> bool:
        if self._path is None:
            return False
        return self._path.exists()

    def make_ready(self):
        self.download()
        self.extract()

    # Handles the downloading of dependencies, including checking if a file needs to be updated
    def download(self):
        with urllib.request.urlopen(urllib.request.Request(self.url, method='HEAD')) as response:
            remote_size = int(response.getheader('Content-Length'))
            remote_modified = datetime.datetime.strptime(response.getheader('Last-Modified'),
                                                         '%a, %d %b %Y %H:%M:%S %Z')
            if self.file_name is None:
                headers = response.headers
                self.file_name = headers.get_filename()
        if self.file_name is None:
            url_parsed = urllib.parse.urlparse(self.url)
            path = PurePosixPath(urllib.parse.unquote(url_parsed.path))
            self.file_name = path.name
        if not self.file_name:
            raise ValueError("Could not divine a file name for the download")
        self._download_path = LAUNCHER_DOWNLOADS / self.file_name

        if (
                self._download_path.exists() and
                self._download_path.stat().st_size == remote_size and
                self._download_path.stat().st_mtime == remote_modified.timestamp()
        ):
            logger.info(f"{self._download_path.name} is already up to date. Skipping.")
            return

        logger.info(f"Downloading {self._download_path.name} from {self.url}")
        temp_file = self._download_path.parent / f"{self._download_path.name}.tmp"
        with urllib.request.urlopen(self.url) as response:
            with open(temp_file, 'wb') as file:
                for chunk in iter(lambda: response.read(CHUNK_SIZE), b''):
                    file.write(chunk)
                    print('.', end='', flush=True, file=sys.stderr)
            print('', flush=True, file=sys.stderr)
        temp_file.rename(self._download_path)
        os.utime(self._download_path, times=(remote_modified.timestamp(), remote_modified.timestamp()))
        logger.debug(f"Saved as {self._download_path.name}")

    # Handles extracting downloaded dependencies and organizing the extracted files
    def extract(self):
        if not self.file_name:
            raise ValueError("file_name must be set")

        stripped = None
        for name, extensions, description in shutil.get_unpack_formats():
            for extension in extensions:
                if self.file_name.endswith(extension):
                    stripped = self.file_name.rstrip(extension)
        if not stripped:
            raise Exception(f"Failed to strip extension from {self.file_name}: Extension not supported by shutil")
        self._path = LAUNCHER_RUNTIME / stripped
        work_extract_path = LAUNCHER_WORK / stripped

        if self.path.exists():
            logger.info(f"{self.path.absolute()} already exists. Skipping.")
            return

        if work_extract_path.exists():
            logger.info(f"{work_extract_path.absolute()} already exists. Removing...")
            shutil.rmtree(work_extract_path.absolute())
        work_extract_path.mkdir(exist_ok=True)

        logger.info(f"Extracting {self.download_path.absolute()} into {work_extract_path.absolute()}")
        shutil.unpack_archive(filename=self.download_path.absolute(), extract_dir=work_extract_path.absolute())

        # Test if the archive contained a directory and nothing else
        single_directory = False
        delete_leftover = False
        for index, path in enumerate(work_extract_path.iterdir()):
            if index == 0 and path.is_dir():
                single_directory = path
                delete_leftover = work_extract_path
            else:
                single_directory = False
                break
        if single_directory:
            work_extract_path = single_directory

        shutil.move(work_extract_path.absolute(), self.path)
        if delete_leftover:
            delete_leftover.rmdir()

    @property
    def download_path(self) -> Path:
        return self._download_path

    @property
    def path(self) -> Path:
        return self._path

# Specializes the Dependency class for JCEF, including setting executable permissions for helper binaries
class JcefDependency(Dependency):
    def extract(self):
        super().extract()

        logger.info("Setting jcef_helper executable bit")
        jcef_helper = self.path / "jcef_helper"
        if jcef_helper.exists():
            jcef_helper.chmod(jcef_helper.stat().st_mode | stat.S_IEXEC)

# Specializes the Dependency class for the Wurm client, which is a JAR file that only needs to be copied
class ClientDependency(Dependency):
    "The Client is a .jar file that does not need to be extracted, just copied"

    def extract(self):
        if not self.file_name:
            raise ValueError("file_name must be set")

        self._path = LAUNCHER_CLIENTS / self.file_name
        needs_replacement = (
                not self.path.exists() or
                sha256sum(self.path) != sha256sum(self.download_path)
        )
        if needs_replacement:
            shutil.copy(self.download_path.absolute(), self.path.absolute())

# Defines the Tkinter-based GUI for the launcher, allowing users to select client configurations and launch the game
def launch_gui():
    root = tk.Tk()
    root.title("WO_Launcherx2 GUI")
    root.geometry("400x300")

    def on_launch():
        selected_client = client_var.get()
        selected_options = options_var.get()
        steam_integration = steam_var.get()
        save_config(selected_client, selected_options, steam_integration)
        launch_client(selected_client, selected_options, steam_integration)

    client_var = tk.StringVar(value="Live")
    options_var = tk.StringVar(value="Default")
    steam_var = tk.BooleanVar()

    ttk.Label(root, text="Client:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
    client_entry = ttk.Entry(root, textvariable=client_var)
    client_entry.grid(row=0, column=1, padx=10, pady=10)

    ttk.Label(root, text="Options:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
    options_entry = ttk.Entry(root, textvariable=options_var)
    options_entry.grid(row=1, column=1, padx=10, pady=10)

    steam_check = ttk.Checkbutton(root, text="Steam Integration", variable=steam_var)
    steam_check.grid(row=2, column=0, columnspan=2, padx=10, pady=10)

    launch_button = ttk.Button(root, text="Launch", command=on_launch)
    launch_button.grid(row=3, column=0, columnspan=2, pady=20)

    root.mainloop()

# Saves the selected client, options, and Steam integration settings into a configuration file
def save_config(client, options, steam):
    config = configparser.ConfigParser()
    config.read_dict(LAUNCHER_CONFIG_DEFAULT)
    config['CLIENT']['Name'] = client
    config['LAUNCH-DEFAULT']['Options'] = options
    config['DEFAULT']['Steam'] = str(steam)

    if not LAUNCHER_CONFIG_FILE.parent.exists():
        LAUNCHER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LAUNCHER_CONFIG_FILE.open('w') as configfile:
        config.write(configfile)

# Loads the configuration from the configuration file, or uses default settings if the file does not exist
def load_config():
    config = configparser.ConfigParser()
    config.read_dict(LAUNCHER_CONFIG_DEFAULT)
    if LAUNCHER_CONFIG_FILE.exists():
        config.read(LAUNCHER_CONFIG_FILE)
    return config

# Handles launching the Wurm Online client, including preparing dependencies and setting environment variables
def launch_client(client_name, options, steam):
    config = load_config()
    manifest = Manifest(WURM_MANIFEST_URL)

    # Prepare dependencies
    jcef = JcefDependency(url=jcef_from_manifest(manifest)['url'])
    if not jcef.is_ready():
        jcef.make_ready()
    config.set('JCEF', 'Path', str(jcef.path))

    jdk = JdkDependency(major_version=config['JDK'].getint('Version'))
    if not jdk.is_ready():
        jdk.make_ready()
    config.set('JDK', 'Path', str(jdk.path))

    jfx = JfxDependency(version=config['JFX']['Version'])
    if not jfx.is_ready():
        jfx.make_ready()
    config.set('JFX', 'Path', str(jfx.path))

    client_manifest = [client for client in manifest['clients'] if client['name'] == client_name]
    if not client_manifest:
        logger.critical(f"Could not find a Client with the name of '{client_name}'")
        sys.exit(1)
    client = ClientDependency(url=client_manifest[0]['url'])
    if not client.is_ready():
        client.make_ready()

    # Save updated config
    with LAUNCHER_CONFIG_FILE.open('w') as configfile:
        config.write(configfile)

    # Launch client
    launch_params = [
        jdk.path / "bin" / "java",
        *options.split(),
        "--module-path", str(jfx.path / "lib"),
        "--add-modules", "ALL-MODULE-PATH",
        "--add-exports=javafx.web/com.sun.javafx.webkit=ALL-UNNAMED",
        "--add-exports=javafx.web/com.sun.webkit=ALL-UNNAMED",
        "--add-exports=javafx.web/com.sun.webkit.graphics=ALL-UNNAMED",
        "-cp", str(client.path),
        "com.wurmonline.client.launcherfx.WurmLaunchWrapper",
    ]
    if steam:
        launch_params.append("-steam")
    os.environ['JAVA_HOME'] = str(jdk.path)
    os.environ['LD_LIBRARY_PATH'] = str(jcef.path) + (":" + os.environ['LD_LIBRARY_PATH'] if 'LD_LIBRARY_PATH' in os.environ else '')
    logger.info("Starting Wurm...")
    subprocess.run(launch_params, stdout=sys.stdout, stderr=sys.stderr)

# Finds the appropriate JCEF dependency from the manifest based on the platform architecture
def jcef_from_manifest(manifest):
    jcefs = [jcef for jcef in manifest['dependencies'] if jcef['name'] == 'jcef-natives']
    platform = get_wurm_arch_identifier()
    jcef = [jcef for jcef in jcefs if jcef['platform'] == platform]
    if jcef:
        return jcef[0]
    else:
        raise Exception(f"No JCEF libraries found for {platform}")

# Determines the platform and architecture identifier for downloading the correct dependencies
def get_wurm_arch_identifier() -> str:
    system = platform.system().lower()
    arch = platform.machine()
    if arch in ('x86_64', 'AMD64'):
        arch = '64'
    elif arch == 'x86':
        arch = '32'
    else:
        raise Exception(f"Unsupported architecture: {arch}")
    return f"{system}{arch}"

# Handles retrieving and caching the manifest file, which contains information about available dependencies
class Manifest:
    def __init__(self, manifest_url):
        self.manifest_url = manifest_url

    @lru_cache(1)
    def _manifest(self) -> dict:
        logger.debug(f"Requesting manifest from {WURM_MANIFEST_URL}")
        with urllib.request.urlopen(self.manifest_url) as response:
            return json.loads(response.read().decode('utf-8'))

    def __getitem__(self, item):
        return self._manifest()[item]

# The main entry point of the script, which parses command line arguments, ensures necessary directories exist, and either launches the GUI or the client based on the arguments
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action="store_true")
    parser.add_argument('-q', '--quiet', action='store_true')
    parser.add_argument('-u', '--update-deps', action='store_true', help="Update dependencies to the latest version")
    parser.add_argument('-l', '--list', action='store_true', help="List available clients and options")
    parser.add_argument('-c', '--client', nargs='?', const='1', default="Live",
                        help="Use this Client. Quote your spaces properly! (Default: Live)")
    parser.add_argument('-o', '--options', nargs='?', const='1', default="Default",
                        help="Use these client options (Default: Default)")
    parser.add_argument('-n', '--no-launch', action='store_true', help="Do not launch Wurm")
    parser.add_argument('-s', '--steam', action='store_true', help="Use Steam integration")
    parser.add_argument('--gui', action='store_true', help="Launch the GUI")

    args, unknown_args = parser.parse_known_args()
    logger.setLevel(logging.INFO)
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if args.quiet:
        logger.setLevel(logging.CRITICAL)

    logger.debug(f"WO_Launcherx2 running on {platform.system()} ({platform.machine()})")

    # Ensure required directories exist
    for folder in (LAUNCHER_RUNTIME, LAUNCHER_WORK, LAUNCHER_CLIENTS, LAUNCHER_DOWNLOADS):
        if not folder.exists():
            logger.debug(f"Creating {folder.name}")
            folder.mkdir(parents=True, exist_ok=True)

    if args.gui:
        launch_gui()
    else:
        if not args.no_launch:
            launch_client(args.client, args.options, args.steam)
        elif args.update_deps:
            # Logic to update dependencies
            manifest = Manifest(WURM_MANIFEST_URL)
            jcef = JcefDependency(url=jcef_from_manifest(manifest)['url'])
            if not jcef.is_ready():
                jcef.make_ready()
            jdk = JdkDependency(major_version=LAUNCHER_CONFIG_DEFAULT['JDK']['Version'])
            if not jdk.is_ready():
                jdk.make_ready()
            jfx = JfxDependency(version=LAUNCHER_CONFIG_DEFAULT['JFX']['Version'])
            if not jfx.is_ready():
                jfx.make_ready()

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
import cgi
import shutil
import hashlib
from functools import lru_cache
import subprocess

logger = logging.getLogger('wurm-ll')
ch = logging.StreamHandler()
f = logging.Formatter('%(message)s')
logger.addHandler(ch)
CHUNK_SIZE = 1048576  # 1MiB
WURM_MANIFEST_URL = "http://client.wurmonline.com/manifest.php"

LAUNCHER_ROOT = Path(__file__).parent
LAUNCHER_DOWNLOADS = LAUNCHER_ROOT / "downloads"
LAUNCHER_RUNTIME = LAUNCHER_ROOT / "runtime"
LAUNCHER_CLIENTS = LAUNCHER_ROOT / "clients"
LAUNCHER_WORK = LAUNCHER_ROOT / "work"
LAUNCHER_CONFIG_FILE = LAUNCHER_ROOT / "config.ini"

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
        'Version': '17.0.2'
    },
    'JCEF': {}
}


def sha256sum(file: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file.absolute(), 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


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


    def download(self):
        with urllib.request.urlopen(urllib.request.Request(self.url, method='HEAD')) as response:
            remote_size = int(response.getheader('Content-Length'))
            remote_modified = datetime.datetime.strptime(response.getheader('Last-Modified'),
                                                         '%a, %d %b %Y %H:%M:%S %Z')
            if self.file_name is None:
                try:
                    value, params = cgi.parse_header(response.getheader('Content-Disposition'))
                    self.file_name = params['filename']
                except:
                    pass
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


class JcefDependency(Dependency):
    def extract(self):
        super().extract()

        logger.info("Setting jcef_helper executable bit")
        jcef_helper = self.path / "jcef_helper"
        if jcef_helper.exists():
            jcef_helper.chmod(jcef_helper.stat().st_mode | stat.S_IEXEC)


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


class JdkDependency(Dependency):
    RELEASE_API = 'https://api.adoptium.net/v3/assets/feature_releases'

    def _url(self):
        pass

    def __init__(self, major_version: int, *args, **kwargs):

        # TODO: Move all this to self.download() instead so __init__() does not query the network
        # TODO: self.is_ready() should not require a network call

        arch = platform.machine()
        query_arch = None
        if arch in ('x86_64', 'AMD64'):
            query_arch = 'x64'
        if arch == 'x86':
            query_arch = 'x86'
        if query_arch is None:
            raise Exception(f"{arch} is unsupported")

        operating_system = platform.system()
        supported_os = ('Linux', 'Windows')
        if operating_system not in supported_os:
            raise ValueError(f"os must be one of {' '.join(supported_os)}")

        self.major_version = major_version
        self.RELEASE_API_ENDPOINT = f"{self.RELEASE_API}/{major_version}/ga?"

        params = {
            'architecture': query_arch,
            'os': operating_system.lower(),
            'project': 'jdk',
            'image_type': 'jdk',
            'heap_size': 'normal',
            'sort_method': 'DATE'
        }
        url = self.RELEASE_API_ENDPOINT + urllib.parse.urlencode(params)
        headers = {
            'accept': 'application/json',
            'User-Agent': 'Wurm-LauncherLauncher 0.1'
        }
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as response:
            jres = json.loads(response.read().decode('utf-8'))
        jre = jres[0]['binaries'][0]
        self.sha256 = jre['package']['checksum']
        logger.info(f"Newest available JRE is {jre['package']['name']}")

        super().__init__(url=jre['package']['link'], file_name=jre['package']['name'], *args, **kwargs)

    def download(self):
        super().download()
        logger.info(f"Comparing checksums")
        download_checksum = sha256sum(self.download_path)
        if not self.sha256 == download_checksum:
            logger.critical(f"Downloaded checksum for {self.file_name} does not match!")
            logger.info(f"Downloaded: {download_checksum}")
            logger.info(f"Should be:  {self.sha256}")
            sys.exit(1)


class JfxDependency(Dependency):
    def __init__(self, version: str = None, *args, **kwargs):

        arch = platform.machine()
        query_arch = None
        if arch in ('x86_64', 'AMD64'):
            query_arch = 'x64'
        if arch == 'x86':
            query_arch = 'x86'
        if query_arch is None:
            raise Exception(f"{arch} is unsupported")

        file_name = f"openjfx-{version}_{platform.system().lower()}-{query_arch}_bin-sdk.zip"
        url = f"https://download2.gluonhq.com/openjfx/{version}/" + file_name

        super().__init__(url=url, file_name=file_name, *args, **kwargs)


def get_wurm_arch_identifier() -> str:
    system = None
    if platform.system() == 'Linux':
        system = 'linux'
    if platform.system() == 'Windows':
        system = 'win'
    if platform.system() == 'Java':
        raise Exception("What the hell")
    if not system:
        raise Exception(f"Sorry, I have no idea what {platform.system()} is")

    arch = None
    if platform.machine() in ('x86_64', 'AMD64'):
        arch = '64'
    if platform.machine() == 'x86':
        arch = '32'
    if not arch:
        raise Exception(f"Sorry, I have no idea what {platform.machine()} is")

    return system + arch


def jcef_from_manifest(manifest):
    jcefs = [jcef for jcef in manifest['dependencies'] if jcef['name'] == 'jcef-natives']
    platform = get_wurm_arch_identifier()
    jcef = [jcef for jcef in jcefs if jcef['platform'] == platform]
    if jcef:
        return jcef[0]
    else:
        raise Exception(f"No JCEF libraries found for {platform}")


def launch_options(config: configparser.ConfigParser)->dict:
    config_launch_sections = (config[section] for section in config.sections() if section.startswith('LAUNCH-'))
    return {
        entry['Name']: entry['Options'].split(' ') for entry in config_launch_sections
    }


def do_list(args, manifest, config):
    options = launch_options(config)

    first_column_maxwidth = max(
        max((len(client['name']) for client in manifest['clients'])),
        max((len(name) for name in options.keys()))
    )
    print ("--- Clients ---")
    for client in manifest['clients']:
        print(f"{client['name']:{first_column_maxwidth}}\t{client['url'] if args.verbose else ''}")
    print("--- Options ---")
    for key, option in options.items():
        print(f"{key:{first_column_maxwidth}}\t{' '.join(option)}")
    sys.exit(0)


def do_launch(args, manifest, config, steam: bool = False):

    selected_options = args.options
    options = launch_options(config).get(selected_options)
    if options is None:
        opt_strings = [f"\"{opt}\"" for opt in launch_options(config).keys()]
        logger.critical(f"\"{selected_options}\" is invalid. Possible values: {' '.join(opt_strings)}")
        sys.exit(1)

    launch_params = [
        jdk.path / "bin" / "java",
        *options,
        "--module-path", str(jfx.path.absolute() / "lib"),
        "--add-modules", "ALL-MODULE-PATH",
        "--add-exports=javafx.web/com.sun.javafx.webkit=ALL-UNNAMED",
        "--add-exports=javafx.web/com.sun.webkit=ALL-UNNAMED",
        "--add-exports=javafx.web/com.sun.webkit.graphics=ALL-UNNAMED",
        "-cp", str(client.path.absolute()),
        "com.wurmonline.client.launcherfx.WurmLaunchWrapper",
    ]
    if steam:
        launch_params.append("-steam")
    launch_params.append("hash=firsthash")

    os.environ['JAVA_HOME'] = str(jdk.path.absolute())
    if os.environ.get('LD_LIBRARY_PATH', None):
        os.environ['LD_LIBRARY_PATH'] = f"{str(jcef.path.absolute())};{os.environ['LD_LIBRARY_PATH']}"
    else:
        os.environ['LD_LIBRARY_PATH'] = str(jcef.path.absolute())

    if steam:
        os.environ['SteamAppId'] = "1179680"

    logger.info("Starting Wurm...")

    wurm = subprocess.run(launch_params, stdout=sys.stdout, stderr=sys.stdout)


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

    args, unknown_args = parser.parse_known_args()
    logger.setLevel(logging.INFO)
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if args.quiet:
        logger.setLevel(logging.CRITICAL)

    logger.debug(f"Wurm Launcher Launcher running on {platform.system()} ({platform.machine()})")

    manifest = Manifest(WURM_MANIFEST_URL)

    config = configparser.ConfigParser()
    config.read_dict(LAUNCHER_CONFIG_DEFAULT)
    if LAUNCHER_CONFIG_FILE.exists():
        logger.debug(f"Reading configuration from {LAUNCHER_CONFIG_FILE.absolute()}")
        config.read(LAUNCHER_CONFIG_FILE.absolute())
    else:
        logger.debug(f"Writing default configuration to {LAUNCHER_CONFIG_FILE.absolute()}")
        with LAUNCHER_CONFIG_FILE.open('w') as f:
            config.write(f)

    for folder in (LAUNCHER_RUNTIME, LAUNCHER_WORK, LAUNCHER_CLIENTS, LAUNCHER_DOWNLOADS):
        if not folder.exists():
            logger.debug(f"Creating {folder.name}")
            folder.mkdir(exist_ok=True)

    if args.list:
        do_list(args, manifest, config)

    if config.get('JCEF', 'Path', fallback=None):
        jcef_path = Path(config.get('JCEF', 'Path'))
    else:
        jcef_path = None
    jcef = JcefDependency(url=jcef_from_manifest(manifest)['url'], path=jcef_path)
    if not jcef.is_ready():
        jcef.make_ready()
    config.set('JCEF', 'Path', str(jcef.path))


    if config.get('JDK', 'Path', fallback=None):
        jdk_path = Path(config.get('JDK', 'Path'))
    else:
        jdk_path = None
    jdk = JdkDependency(major_version=config['JDK'].getint('version'), path=jdk_path)
    if not jdk.is_ready():
        jdk.make_ready()
    config.set('JDK', 'Path', str(jdk.path))

    if config.get('JFX', 'Path', fallback=None):
        jfx_path = Path(config.get('JFX', 'Path'))
    else:
        jfx_path = None
    jfx = JfxDependency(version=config['JFX']['version'], path=jfx_path)
    if not jfx.is_ready():
        jfx.make_ready()
    config.set('JFX', 'Path', str(jfx.path))


    client_manifest = [client for client in manifest['clients'] if client['name'] == args.client]
    if not client_manifest:
        logger.critical(f"Could not find a Client with the name of '{args.client}'")
        sys.exit(1)
    client = ClientDependency(url=client_manifest[0]['url'])
    if not client.is_ready():
        client.make_ready()

    with LAUNCHER_CONFIG_FILE.open('w') as f:
        config.write(f)

    if args.no_launch:
        sys.exit(0)

    do_launch(args, manifest, config, steam = args.steam)
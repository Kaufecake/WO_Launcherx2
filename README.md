# WO_Launcherx2

**A modernized and user-friendly launcher for Wurm Online.**

The WO_Launcherx2 project is a refreshed and improved version of the original Wurm Launcher Launcher (wurm-ll), originally created by Bato (link: [https://gitlab.com/fb0/wurm-ll](https://gitlab.com/fb0/wurm-ll)). This new version aims to provide a smoother, more accessible experience while respecting user privacy and modern standards.

## Key Improvements
- **User Privacy**: Eliminated unnecessary third-party network connections to protect user privacy.
- **Preserve Client Binaries**: Changing the desired client no longer overwrites the old client binary.
- **Installation Improvements**: Added a `setup.py` for a more streamlined installation process.
- **Respect XDG Spec**: Configurations and data files are now stored in locations consistent with the XDG Base Directory Specification.
- **Graphical User Interface**: Added a new Tk/Tcl GUI for an easier and more intuitive user experience.
- **Windows Executable**: Added the ability to compile the launcher into a standalone `.exe` file with an embedded Python interpreter for Windows users.

## Features
- Bootstrap and launch a Wurm Online client from scratch, including Java, JFX, and other dependencies.
- Launch Wurm with a variety of pre-defined Java options and alternate client binaries.
  - Supports alternate garbage collectors like Shenandoah for smoother frame rates.
- Launch with Steam integration (`-s`) to log in Steam characters (requires Steam to be running).
- Works on Linux and Windows.
- Uses only the Python standard library for simplicity and maintainability.

## Prerequisites
- Python 3 (>= 3.7) if not using the `.exe` version.

## Usage
Simply run `WO_Launcherx2.py`, either directly or from a terminal. `WO_Launcherx2.py -h` prints a list of options.

When run for the first time, `WO_Launcherx2.py` will automatically bootstrap its environment.

## Known Issues
- Inconsistent logging behavior.
- Limited testing on macOS, functionality may vary.

## Future Work
- Improve the logging system for better debugging and maintenance.
- Create `.desktop` files on Linux and shortcuts on Windows for easier access.
- Expand testing to macOS.

## Acknowledgments
WO_Launcherx2 is inspired by Bato's original project, Wurm Launcher Launcher ([wurm-ll](https://gitlab.com/fb0/wurm-ll)). Bato's contributions laid the foundation for this enhanced version, and this project pays tribute to his pioneering work in making Wurm Online more accessible to the community.

## Repository
The WO_Launcherx2 project is open source and hosted on GitHub: [https://github.com/Kaufecake/WO_Launcherx2](https://github.com/Kaufecake/WO_Launcherx2). Contributions, issues, and suggestions are welcome!

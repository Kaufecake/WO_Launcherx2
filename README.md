Wurm Launcher Launcher
===

Annoyed with the old and buggy version of Java bundled with Wurm Online I set out to get the game running on modern Java. What started as a small shell script eventually grew as I hacked together more features to work around further annoyances.

I am releasing it in case anyone else finds it useful. I will maintain it as long I keep using it and/or until it is made obsolete by the Wurm developers.

Features
---
 - Bootstrap and launch a Wurm Online client from scratch (Java, JFX, other dependencies)
 - Launch Wurm with a variety of pre-defined Java options and alternate client binaries
     - Of note: Alternate garbage collectors like Shenandoah are supported for a smoother frame rate
 - Launch with Steam integration (`-s`) to log in Steam characters (needs Steam to be running)
 - Works on Linux, probably works on Windows
 - Uses only the Python standard library

Prerequisites
---
- Python 3 >= 3.6

Usage
---
Simply run `wurm-ll.py`, either directly or from a terminal. `wurm-ll.py -h` prints a list of options.

When run for the first time `wurm-ll.py` will automatically bootstrap its environment in the folder the file is in.

Known Issues
---

- The code is a horrible mess of hacks
- Each start of the launcher leads to a few unnecessary network connections to third parties
- Changing the desired client overwrites the old client binary
- The code is a horrific mess
- No setup.py or similar
- Does not respect XDG spec, and it probably should
- No versioning, no releases
- Logging is very inconsistent

Future work
---
After fixing the above, I plan to work on the following:

- Create .desktop files on Linux, Shortcuts on Windows
- Windows: Perhaps compile the script to an .exe with an embedded Python interpreter
- Use Tk/Tcl to provide a simple GUI

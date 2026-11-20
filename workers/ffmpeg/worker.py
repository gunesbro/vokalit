"""Video export tool for Vokalit: brings the FFmpeg program (imageio-ffmpeg). The app runs FFmpeg itself on local
files when it exports a dub as a video; this script only checks the install.

python worker.py --download  check that FFmpeg runs (used by Install; nothing is downloaded beyond the package)
python worker.py --selftest  print FFmpeg's version
"""
import subprocess
import sys


def version():
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True, check=True).stdout
    return exe, out.splitlines()[0] if out else "unknown"


def main():
    if "--download" in sys.argv or "--selftest" in sys.argv:
        exe, line = version()
        print(f"{line} ({exe})")
        return
    print("This tool has no worker: the app runs FFmpeg itself.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

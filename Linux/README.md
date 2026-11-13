# PicoPod for Linux

Requires Python 3.12+, Tk, venv support and a graphical desktop. On Debian/Ubuntu,
install `python3-tk` and `python3-venv` using your package manager first.

Run from this folder:

```sh
sh setup.sh
sh run.sh
```

For the offline demo: `sh run.sh --preview`. Setup creates **PicoPod.desktop** with
`Terminal=false` for launching just the GUI. Your desktop may require selecting
**Allow Launching** on that file. Keep the folder somewhere writable by your user.

Song management, saved libraries/playlists, offline preview, live USB control and
Pico firmware/metadata uploads are included. Select the Pico's Linux serial device
(usually `/dev/ttyACM0`); your user needs permission to access that device. Depending
on your distribution this uses the `dialout` or `uucp` group, followed by logging
out/in. Close other serial applications before firmware or metadata transfers.

**Upload everything** supports removable PICOPOD cards on Linux too: existing
FAT32 cards use verified incremental updates; other filesystems require explicit
erase confirmation and desktop authorization before FAT32 formatting. Install
`udisks2`, `util-linux`, `dosfstools` and GLib's `gdbus` tool (Debian/Ubuntu:
`libglib2.0-bin`). A running desktop polkit authentication agent is required for
privileged operations. Readers must expose a disk serial/WWN and partition UUID;
system, read-only, layered and multi-partition disks are refused. Card readers
without reliable identities can use **Export only** to an already-mounted FAT32
card, then **Upload library.json** with that exported manifest. Indexed catalogs
are uploaded automatically when their `.bin` file is beside the manifest.

This is a source package with Linux setup/launch scripts, not a bundled Linux
Python runtime. It has not been run on a physical Linux desktop in this session.
Your library starts empty; add MP3s using their Linux paths. State saves locally
under `userdata`. See **PROJECT_GUIDE.md** for the common player/hardware guide.

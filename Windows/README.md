# PicoPod for Windows

For another computer, copy **PicoPod-Windows-x64.zip**, extract the entire folder,
then open **PicoPod.exe**. The standalone build includes Python and dependencies;
it requires neither Codex nor a Python installation. Keep `_internal` beside the exe.
**Launch PicoPod.vbs** and **Preview PicoPod.vbs** prefer this bundled build when
present and launch without a terminal window.

The remaining source files are for development. For a source-only installation,
install Python 3.12+ with Tcl/Tk on that PC and run **Setup PicoPod.cmd**. Never copy
a `.venv` between computers: its interpreter paths are machine-specific.

This folder includes the manager, Pico firmware, Windows SD preparation helper,
requirements and launchers. Firmware installation and live USB control work from
this copy. Card erasing still requires its explicit confirmation.

Your saved song list/playlists were copied into `userdata` if available. Original
MP3 locations remain unchanged: the audio collection and Python runtime are not
duplicated. Keep the originals available or add local files on another computer.
This copy saves future changes into its own `userdata` folder.

See **PROJECT_GUIDE.md** for hardware and player instructions.

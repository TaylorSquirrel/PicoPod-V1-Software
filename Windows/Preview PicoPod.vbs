Option Explicit
Dim shell, files, folder, python, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, "PicoPodPortable\PicoPod.exe")
If files.FileExists(python) Then
    command = Chr(34) & python & Chr(34) & " --preview"
    shell.Run command, 1, False
    WScript.Quit
End If
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then python = "pythonw.exe"
shell.CurrentDirectory = folder
command = Chr(34) & python & Chr(34) & " " & Chr(34) & files.BuildPath(folder, "launch_gui.pyw") & Chr(34) & " --preview"
On Error Resume Next
shell.Run command, 1, False
If Err.Number <> 0 Then MsgBox "Could not start the PicoPod preview." & vbCrLf & Err.Description, vbExclamation, "PicoPod"

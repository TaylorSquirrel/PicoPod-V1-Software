Option Explicit
Dim shell, files, folder, python, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then python = "pythonw.exe"
shell.CurrentDirectory = folder
command = Chr(34) & python & Chr(34) & " " & Chr(34) & files.BuildPath(folder, "launch_gui.pyw") & Chr(34)
On Error Resume Next
shell.Run command, 1, False
If Err.Number <> 0 Then
    MsgBox "Could not start PicoPod. Install Python with Tk support and the project dependencies." & vbCrLf & Err.Description, vbExclamation, "PicoPod"
End If

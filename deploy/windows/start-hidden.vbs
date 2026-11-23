Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoDir = fso.GetAbsolutePathName(scriptDir & "\..\..")

venvPython = repoDir & "\.venv\Scripts\python.exe"
If Not fso.FileExists(venvPython) Then
    venvPython = "python"
End If

logFile = repoDir & "\logs\agy-router.log"
cmd = Chr(34) & venvPython & Chr(34) & " " & Chr(34) & repoDir & "\run.py" & Chr(34) & " --log-file " & Chr(34) & logFile & Chr(34)

shell.CurrentDirectory = repoDir
shell.Run cmd, 0, False

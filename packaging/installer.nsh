!define WEBFA_MIN_TEMP_FREE_MB 4096

!macro customInit
  System::Call 'kernel32::GetDiskFreeSpaceEx(t "$TEMP", *l.r0, *l, *l) i.r1'
  ${If} $1 == 0
    MessageBox MB_OK|MB_ICONSTOP "WebFA could not determine free space on the Windows temporary drive. Check $TEMP, then try again." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
  System::Int64Op $0 / 1048576
  Pop $0
  ${If} $0 < ${WEBFA_MIN_TEMP_FREE_MB}
    MessageBox MB_OK|MB_ICONSTOP "WebFA needs at least 4 GB free on the Windows temporary drive before installation can start. Free space on $TEMP, then try again." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
!macroend

!macro customUnInstall
  # The cached installer is release machinery, not user-created WebFA data.
  # Remove only the known installer file and its directory if now empty.
  !ifdef APP_INSTALLER_STORE_FILE
    SetShellVarContext current
    Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    ${GetParent} "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}" $R0
    RMDir "$R0"
    ${if} $installMode == "all"
      SetShellVarContext all
    ${endif}
  !endif
!macroend

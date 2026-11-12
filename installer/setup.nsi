Unicode true
RequestExecutionLevel user
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "generated\version.nsh"

Name "DC Assistant"
OutFile "..\dist\DC-Assistant-Setup-v${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\DCAssistant"
InstallDirRegKey HKCU "Software\DC Assistant" "InstallDir"
SetCompressor /SOLID lzma
CRCCheck on
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "DC Assistant"
VIAddVersionKey /LANG=1033 "FileDescription" "DC Assistant Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" ""

!define MUI_ICON "..\dc_assistant\assets\dc-assistant.ico"
!define MUI_UNICON "..\dc_assistant\assets\dc-assistant.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets\sidebar.bmp"
!define MUI_BGCOLOR "0B1426"
!define MUI_TEXTCOLOR "F3F7FC"
!define MUI_INSTFILESPAGE_COLORS "F3F7FC 0B1426"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "DC Assistant"
!define MUI_WELCOMEPAGE_TEXT "تثبيت DC Assistant على جهازك.$\r$\n$\r$\nالمشاريع والإعدادات محفوظة في قاعدة بيانات محلية ثابتة، خارج فولدر البرنامج.$\r$\n$\r$\nأغلق البرنامج قبل تثبيت تحديث جديد."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\DC-Assistant.exe"
!define MUI_FINISHPAGE_RUN_TEXT "فتح DC Assistant"
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "سيحذف هذا الإجراء ملفات البرنامج واختصاراته. بيانات المشاريع والنسخ الاحتياطية ستظل محفوظة."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Arabic"

Var TestMode

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "هذه النسخة تحتاج Windows 64-bit."
    Abort
  ${EndIf}
  StrCpy $TestMode 0
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/TEST" $1
  ${IfNot} ${Errors}
    StrCpy $TestMode 1
  ${EndIf}
FunctionEnd

Function .onVerifyInstDir
  ${GetRoot} "$INSTDIR" $0
  ${If} "$INSTDIR" == "$0\"
    Abort
  ${EndIf}
FunctionEnd

Section "DC Assistant"
  Call .onVerifyInstDir
  SetOverwrite on
  !include "generated\payload.nsh"
  SetOutPath "$INSTDIR"
  WriteINIStr "$INSTDIR\install-mode.ini" "DC Assistant" "Version" "${APP_VERSION}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $TestMode == 0
    CreateDirectory "$SMPROGRAMS\DC Assistant"
    CreateShortcut "$DESKTOP\DC Assistant.lnk" "$INSTDIR\DC-Assistant.exe" "" "$INSTDIR\DC-Assistant.exe" 0
    CreateShortcut "$SMPROGRAMS\DC Assistant\DC Assistant.lnk" "$INSTDIR\DC-Assistant.exe" "" "$INSTDIR\DC-Assistant.exe" 0
    CreateShortcut "$SMPROGRAMS\DC Assistant\إلغاء التثبيت.lnk" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\DC Assistant" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "DisplayName" "DC Assistant"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "DisplayIcon" "$INSTDIR\DC-Assistant.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant" "NoRepair" 1
  ${EndIf}
SectionEnd

Function un.onInit
  SetShellVarContext current
  StrCpy $TestMode 0
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/TEST" $1
  ${IfNot} ${Errors}
    StrCpy $TestMode 1
  ${EndIf}
FunctionEnd

Section "Uninstall"
  !include "generated\uninstall-files.nsh"
  Delete "$INSTDIR\install-mode.ini"
  Delete "$INSTDIR\Uninstall.exe"
  ${If} $TestMode == 0
    Delete "$DESKTOP\DC Assistant.lnk"
    Delete "$SMPROGRAMS\DC Assistant\DC Assistant.lnk"
    Delete "$SMPROGRAMS\DC Assistant\إلغاء التثبيت.lnk"
    RMDir "$SMPROGRAMS\DC Assistant"
    DeleteRegKey HKCU "Software\DC Assistant"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DCAssistant"
  ${EndIf}
  RMDir "$INSTDIR"
SectionEnd

# Windows용 CalcLens 0.9.0

1. [Windows x64 EXE](https://github.com/a123qsd/calclens/releases/download/v0.9.0/CalcLens-0.9.0-Windows-x64.exe)를 받습니다.
2. EXE를 두 번 클릭합니다. 포함된 파일을 푸는 데 몇 초 걸릴 수 있습니다.
3. 그래핀 구조가 열린 뒤 **CIF 열기**로 파일을 선택하거나 CIF를 창으로 끌어 놓으세요. 앱 창에서 언어를 선택할 수 있습니다.

EXE에 Python과 Qt가 포함되어 있으며 로컬 작업은 오프라인에서 실행됩니다. 앱을 닫으면 작업의 수정 사항을 저장할 수 있습니다. Windows 배포 파일에는 게시자 서명이 없습니다. PowerShell에서 받은 파일을 확인하려면 다음 명령의 출력과 [공개 SHA-256](https://github.com/a123qsd/calclens/releases/download/v0.9.0/SHA256SUMS.txt)을 비교하세요.

```powershell
Get-FileHash .\CalcLens-0.9.0-Windows-x64.exe -Algorithm SHA256
```

[사용 안내](../../docs/DESKTOP.md) · [배포본 소스](https://github.com/a123qsd/calclens/archive/refs/tags/v0.9.0.zip) · [Windows 빌드 방법](../desktop/windows-portable-build.md) · [라이선스](../../THIRD_PARTY_NOTICES.md) · [0.8.0 브라우저 버전 안내](https://github.com/a123qsd/calclens/blob/v0.8.0/packaging/windows/README.ko.md)

# Windows용 CalcLens 0.9.1

1. [Windows x64 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip)을 받습니다.
2. ZIP 전체를 새 폴더에 풉니다. 압축을 푼 파일 전체를 함께 보관하세요.
3. `runtime` 폴더 옆의 `CalcLens.exe`를 실행합니다. 다음 실행부터 같은 파일을 바로 사용합니다.
4. 그래핀 구조가 열린 뒤 **CIF 열기**로 파일을 선택하거나 CIF를 창으로 끌어 놓으세요. 앱 창에서 언어를 선택할 수 있습니다.

폴더에 Python과 Qt가 포함되어 있습니다. 새 버전은 별도 폴더에 푸세요. 로컬 작업은 오프라인에서 실행됩니다. 앱을 닫으면 작업의 수정 사항을 저장할 수 있습니다. 실행 파일에는 게시자 서명이 없습니다. PowerShell에서 받은 ZIP을 확인하려면 다음 명령의 출력과 [파일별 SHA-256](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt)을 비교하세요.

```powershell
Get-FileHash .\CalcLens-0.9.1-Windows-x64-folder.zip -Algorithm SHA256
```

[사용 안내](../../docs/DESKTOP.md) · [배포본 소스](https://github.com/a123qsd/calclens/archive/refs/tags/v0.9.1.zip) · [Windows 빌드 방법](../desktop/windows-portable-build.md) · [라이선스](../../THIRD_PARTY_NOTICES.md) · [0.8.0 브라우저 버전 안내](https://github.com/a123qsd/calclens/blob/v0.8.0/packaging/windows/README.ko.md)

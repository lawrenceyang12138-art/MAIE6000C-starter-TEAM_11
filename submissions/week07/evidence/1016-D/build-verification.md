# API-mode production build verification

Date: 2026-10-16, Asia/Shanghai. Working directory: `frontend/`.

```powershell
$env:VITE_DATA_MODE='api'
$env:VITE_API_BASE_URL='/api'
npm.cmd run build
```

Exit code 0. Vite 5.4.10 transformed 4910 modules and built in 9.25 seconds:

```text
dist/index.html                   0.47 kB │ gzip:   0.30 kB
dist/assets/index-4rS5Zvaf.css   43.97 kB │ gzip:   9.01 kB
dist/assets/index-CNejqwqa.js   324.56 kB │ gzip: 100.65 kB
```

SHA-256 values read from the resulting local files:

| Repository-relative file | SHA-256 |
| --- | --- |
| `frontend/package-lock.json` | `0e95c347c7c5e777e38b3121f12b8eda36216220566743a37b7199bb48ffe705` |
| `frontend/dist/index.html` | `76aa53b490f663298ba5cf60b1b2ea270a77fc2b3f6264a03be8e7dcbacae98c` |
| `frontend/dist/assets/index-4rS5Zvaf.css` | `19091999c3d4dce7bb89484dbf9b1cd8c1a1bc135bf814e45cd91058b49a8241` |
| `frontend/dist/assets/index-CNejqwqa.js` | `a3e031694aba3c6e78fad7011c6f5528ce6e92d3bb2b509d462fe9648817400c` |

The build was served using `npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`. `browser-contract-report.json` records the separate headless-browser checks against that preview. The screenshots use intercepted fixture responses, not the actual API. No Docker image was built or replaced. Build output remains ignored by Git; the lockfile should accompany source changes.

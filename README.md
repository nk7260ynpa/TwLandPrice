# TwLandPrice

台灣地價視覺化。

## 專案架構

```
TwLandPrice/
├── .gitlab-ci.yml   # GitLab CI/CD：main 更新時自動鏡像同步到 GitHub
└── README.md        # 專案說明
```

## 版本控制與遠端

本專案採雙遠端結構，以自架 GitLab 為主、GitHub 為鏡像：

| 遠端 | 位址 | 角色 |
| --- | --- | --- |
| `origin` | `ssh://git@localhost:2222/nk7260ynpa/TwLandPrice.git` | 主要遠端（GitLab） |
| `github` | `git@github.com:nk7260ynpa/TwLandPrice.git` | 鏡像（GitHub） |

## GitLab → GitHub 自動同步

`.gitlab-ci.yml` 定義 `sync-to-github` 工作：每當有 commit 進入 `main`
（含其他分支 merge 進 `main`）即觸發，將 `main` 分支與標籤推送到 GitHub，
使兩邊程式碼保持一致。

設定需求：

1. **Runner**：GitLab 專案需有可用的 Runner。
2. **CI/CD 變數 `GITHUB_SSH_KEY`**：GitHub Deploy Key 的私鑰內容。
   對應公鑰須加到 GitHub repo 的 *Settings → Deploy keys* 並勾選
   *Allow write access*；建議將變數設為 *Protected*。
3. **網路**：Runner 需能對外連線至 `github.com`（SSH，22 埠）。

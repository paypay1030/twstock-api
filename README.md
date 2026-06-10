# 我的持股管家 API

台股個人投資分析助手後端。所有分析均為機率與風險評估，不保證股價走勢。

## 快速啟動（本機）

```bash
# 1. 建立虛擬環境（建議）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，設定 APP_ENV=development

# 4. 啟動
uvicorn app.main:app --reload --port 8000

# 5. 開啟文件
# http://localhost:8000/docs
```

## 部署到 Railway

### 步驟

1. 前往 [railway.app](https://railway.app) 建立帳號
2. New Project → Deploy from GitHub repo
3. 選擇此專案的 repo
4. Railway 自動偵測 Python，使用 `railway.toml` 設定
5. 在 Variables 頁面設定以下環境變數：

```
APP_ENV=production
ALLOWED_ORIGINS=https://your-frontend.vercel.app
```

6. Deploy 完成後取得 URL，格式如：`https://twstock-api-production.up.railway.app`

### 環境變數說明

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `APP_ENV` | **必填**。`production` = 真實資料，失敗時回傳錯誤 | `development` |
| `ALLOWED_ORIGINS` | **必填**。前端網址，用於 CORS | `http://localhost:3000` |
| `VOLUME_PROFILE_BUCKETS` | Volume Profile 分桶數 | `60` |
| `SIGNAL_RESIST_NEAR` | 距壓力橘燈閾值 | `0.03` |
| `SIGNAL_RESIST_MID` | 距壓力黃燈閾值 | `0.06` |

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/health` | 健康檢查 |
| `GET` | `/api/stock/search?q=` | 搜尋股票 |
| `GET` | `/api/stock/{code}` | 股票基本資訊 |
| `GET` | `/api/stock/{code}/history` | 歷史 K 線 |
| `POST` | `/api/analysis/{code}` | 完整技術分析 |

## 架構說明

```
app/
├── main.py              FastAPI 主程式
├── core/
│   ├── config.py        所有可調整參數（集中管理）
│   └── cache.py         記憶體快取（TTL）
├── routers/
│   ├── stock.py         股票資料 API
│   └── analysis.py      技術分析 API（純技術面，不受個人成本影響）
├── services/
│   ├── stock_fetcher.py Yahoo Finance 串接 + mock fallback
│   ├── volume_profile.py 成交量密集區計算
│   ├── support_resistance.py 支撐壓力主計算
│   ├── risk_engine.py   燈號 + 三因子風險
│   ├── decision_card.py 懶人決策卡生成
│   └── trim_calculator.py 智慧減碼試算
└── utils/
    ├── stock_list.py    台股完整清單（1937 檔）
    └── price_utils.py   升降單位計算
```

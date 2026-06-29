# PubMed 新着論文 自動収集・要約・メール送信システム

指定したキーワード（日本語対応）で PubMed から最新論文を自動取得し、**Gemini AI** による日本語要約と **OpenAlex API** から取得したジャーナルの2年平均被引用数を付与した HTML レポートを定期的にメール送信するバッチ処理システムです。

## 主な機能

- **PubMed 自動検索** — 直近 N 日間の新着論文を自動取得
- **日本語キーワード対応** — 日本語を自動で英語医学用語に変換
- **AI 日本語要約** — Gemini API で抄録を3行に要約
- **ジャーナル被引用数表示** — OpenAlex API から2年平均被引用数を自動取得（キャッシュ機能付き）
- **HTML メールレポート** — 被引用数降順ソート、色分けバッジ付きの見やすいデザイン
- **GitHub Actions 自動実行** — 毎週日曜 JST 9:00 にクラウドで自動実行
- **デバッグモード** — メール送信なしで HTML をローカル出力

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/saruko/PubMed_new_papears.git
cd PubMed_new_papears
```

### 2. Python 環境を準備

```bash
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 3. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を開いて以下を設定:

| 変数 | 説明 | 必須 |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) で取得 | AI 要約時 |
| `ENTREZ_EMAIL` | PubMed API に通知するメールアドレス | Yes |
| `SMTP_SERVER` | SMTP サーバー（例: `smtp.gmail.com`） | メール送信時 |
| `SMTP_PORT` | SMTP ポート（通常 `587`） | メール送信時 |
| `SMTP_USER` | 送信元メールアドレス | メール送信時 |
| `SMTP_PASSWORD` | アプリパスワード | メール送信時 |
| `RECIPIENT_EMAILS` | 送信先（カンマ区切りで複数指定可） | メール送信時 |
| `SEARCH_KEYWORDS` | 検索キーワード（日本語 OK） | — |

## 使い方

### 基本実行

```bash
# デフォルト設定で実行（.env の値を使用）
python main.py

# キーワードを指定
python main.py --keyword "緑内障"

# 英語キーワードも直接指定可能
python main.py --keyword "glaucoma AND treatment"

# 過去3日分だけ取得
python main.py --days 3
```

### デバッグ

```bash
# デバッグモード（メール送信なし → HTML ファイル出力）
python main.py --debug

# 出力先を指定
python main.py --debug --output my_report.html

# ドライラン（論文取得のみ、要約・送信なし）
python main.py --dry-run

# 詳細ログ
python main.py -v
```

### テスト

```bash
python -m pytest tests/test_modules.py -v
```

## GitHub Actions（自動実行）

### Secrets の設定

リポジトリの **Settings > Secrets and variables > Actions** で以下を追加:

- `GEMINI_API_KEY`
- `ENTREZ_EMAIL`
- `SMTP_SERVER`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `RECIPIENT_EMAILS`
- `SEARCH_KEYWORDS`（任意）

### スケジュール

- **自動実行**: 毎週日曜 JST 9:00（UTC 0:00）
- **手動実行**: Actions タブ > 「PubMed 新着論文レポート」> 「Run workflow」

手動実行時はキーワード・日数・デバッグモードを指定できます。

## ファイル構成

```
PubMed_new_papears/
├── main.py                 # エントリーポイント
├── config.py               # 設定管理
├── keyword_translator.py   # 日本語→英語キーワード変換
├── pubmed_fetcher.py       # PubMed データ収集
├── enrichment.py           # AI 要約 & OpenAlex 被引用数取得
├── reporter.py             # HTML 生成 & メール送信
├── requirements.txt        # 依存パッケージ
├── .env.example            # 環境変数テンプレート
├── data/                   # キャッシュ保存先（自動生成）
├── tests/
│   └── test_modules.py     # ユニットテスト
└── .github/
    └── workflows/
        └── weekly_report.yml  # GitHub Actions 定期実行
```

## ライセンス

MIT License

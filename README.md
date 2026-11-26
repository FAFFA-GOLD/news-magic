# AIニュース・デイリーパイプライン

RSS から AI 関連ニュースを毎朝集め、**日本語要約付き**で Notion に保存し、カテゴリ別の**朝ダイジェスト**を自動作成する GitHub Actions 向けパイプラインです。

## できること

- `feeds.yaml` に定義した幅広い AI ソースを巡回（海外ラボ、国内メディア、HN/Lobsters、料金・キャンペーン系キーワード RSS など）
- 新規記事ごとに **日本語要約（2〜4文）・重要度 1〜5・カテゴリ・タグ** を付与（LLM / 未設定時は RSS 要約で代替）
- Notion データベースへ URL 重複なしで保存
- 直近 24 時間分をカテゴリ別・重要度順にまとめた **AIダイジェスト YYYY-MM-DD** を Notion ページとして作成
- （任意）Slack / Discord などへ `DIGEST_WEBHOOK_URL` で投稿
- LLM 失敗時はタグ **要約未処理** を付与し、後から `--reanalyze-fallback` で再要約可能

## クイックスタート

### 1. Gemini API キー（推奨・安価）

1. [Google AI Studio](https://aistudio.google.com/apikey) で API キーを発行
2. GitHub リポジトリの **Settings → Secrets → Actions** に `GEMINI_API_KEY` を登録

デフォルトモデルは `gemini-2.5-flash`（環境変数 `GEMINI_MODEL` で変更可。空の Repository Variable は無視されます）。
Gemini 呼び出しは既定で **4 秒間隔**（`GEMINI_PACE_SECONDS`、無料枠の RPM 対策）。

### 2. Notion インテグレーション

1. [Notion Integrations](https://www.notion.so/my-integrations) でインテグレーションを作成し **Internal Integration Token** を取得 → `NOTION_TOKEN`
2. ダイジェストや DB を置きたい **親ページ** を開き、右上「…」→「コネクト」でインテグレーションを追加
3. 親ページの URL からページ ID をコピー → `NOTION_PARENT_PAGE_ID`
4. ローカルまたは CI で DB を作成:

```bash
export NOTION_TOKEN=secret_...
export NOTION_PARENT_PAGE_ID=xxxxxxxx...
pip install -r requirements.txt
python setup_notion_db.py
```

出力された `NOTION_DATABASE_ID` を GitHub Secrets に登録。

#### Notion プロパティ一覧

| プロパティ | 型 |
|-----------|-----|
| タイトル | title |
| 要約 | rich text |
| 重要度 | number |
| カテゴリ | select（新モデル / ツール・サービス / お得情報・料金 / 研究 / 業界動向 / 国内） |
| タグ | multi-select |
| ソース | select |
| URL | url |
| 公開日 | date |
| 取得日 | date |

### 3. GitHub Secrets（必須・任意）

| Secret / Variable | 必須 | 説明 |
|-------------------|------|------|
| `GEMINI_API_KEY` | 推奨 | 要約用（未設定時は RSS 抜粋のみ） |
| `NOTION_TOKEN` | 本番推奨 | Notion インテグレーション |
| `NOTION_DATABASE_ID` | 本番推奨 | 記事 DB |
| `NOTION_PARENT_PAGE_ID` | 推奨 | ダイジェストページの親 |
| `OPENAI_API_KEY` | 任意 | Gemini が無い場合の互換 API（xAI 等は `OPENAI_BASE_URL` / `OPENAI_MODEL` も） |
| `DIGEST_WEBHOOK_URL` | 任意 | Slack incoming webhook 等 |

Repository **Variables**（任意）: `GEMINI_MODEL`, `GEMINI_PACE_SECONDS`, `OPENAI_BASE_URL`, `OPENAI_MODEL`  
未設定・空文字の Variable はコード側のデフォルトが使われます。

### 4. ローカル dry-run（キー不要）

```bash
pip install -r requirements.txt
python -m ai_news.pipeline --dry-run
```

フィード取得とダイジェスト出力まで動作確認できます。

### 5. フィードの追加・削除

`feeds.yaml` の `feeds` リストに `source` と `url` を追加してください。変更後:

```bash
python scripts/verify_feeds.py
```

## GitHub Actions

ワークフロー: `.github/workflows/ai-news-daily.yml`

- **スケジュール**: 毎日 21:30 UTC（**06:30 JST**）
- **手動実行**: `workflow_dispatch`（`reanalyze_fallback=true` で要約未処理行の再要約＋当日ダイジェスト更新）
- **Python**: 3.12
- **失敗時**: 候補があるのに 0 件保存、または LLM がほぼ全件失敗した場合は exit code 1

### フォールバック記事の再要約

初回実行で Gemini モデル未設定などにより RSS フォールバックになった行（タグ `要約未処理`、または 重要度3＋業界動向）は、次で再処理できます。

```bash
python -m ai_news.pipeline --reanalyze-fallback
```

GitHub Actions では **Run workflow** → `reanalyze_fallback` にチェック。

## コストの目安

- **GitHub Actions**: パブリックリポジトリなら無料枠内が一般的（1 回あたり数分・日 1 回）
- **Gemini Flash**: 新規記事数 × 短文要約。数十件/日想定で **月数円〜数十円程度**（変動あり）
- **Notion**: 無料プランで十分なことが多い

## ディレクトリ構成

```
feeds.yaml              # RSS ソース一覧
ai_news/                # パイプライン本体
setup_notion_db.py      # Notion DB 初回作成
scripts/verify_feeds.py # フィード死活確認
```

## 検証時に落としたソース（代替あり）

公式 RSS が 404/410、またはエントリ 0 のため `feeds.yaml` には含めていません。必要なら Google News ウィジェット RSS 等で代替してください。

- Anthropic / Mistral / Meta AI / xAI の公式ブログ RSS（404 または 403）→ Google News 検索 RSS で代替
- `blog.google/feed/`（パースエラー）→ `blog.google/technology/ai/rss/`
- Microsoft AI ブログ（410）→ Microsoft Research フィード
- Mistral 公式 RSS、Cohere、Replicate、LangChain、Stability AI、Groq、xAI 直接 RSS
- ArXiv cs.AI / cs.LG（当環境では 0 件）
- hnrss の複雑なクエリは 502 になることがあり → シンプルなクエリに変更済み
- GIGAZINE RSS（0 件・パース失敗）
- VentureBeat（429 レート制限）
- Import AI Substack（403）

## ライセンス

リポジトリオーナーに従います。
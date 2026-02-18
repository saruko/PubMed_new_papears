"""PubMed 新着論文レポートシステム — メインエントリーポイント。

使用例:
    # デフォルト設定で実行（.env から読み込み）
    python main.py

    # キーワードと日数を指定
    python main.py --keyword "緑内障" --days 3

    # デバッグモード（メール送信せず HTML をファイル出力）
    python main.py --debug

    # ドライラン（論文取得のみ、要約・送信なし）
    python main.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import Config
from enrichment import enrich_articles
from keyword_translator import translate_keyword
from pubmed_fetcher import get_articles
from reporter import build_html_report, send_email


def setup_logging(verbose: bool = False) -> None:
    """ロギングを設定する。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="PubMed 新着論文レポートシステム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python main.py                          # .env の設定で実行
  python main.py --keyword "緑内障"        # キーワード指定
  python main.py --keyword "glaucoma"      # 英語キーワードも可
  python main.py --days 3 --debug          # 3日分をデバッグモードで
  python main.py --dry-run -v             # 論文取得のみ（詳細ログ）
        """,
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default=None,
        help="検索キーワード（日本語 or 英語）。未指定時は .env の値を使用。",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="過去何日分の論文を取得するか。未指定時は .env の値を使用。",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="最大取得件数。",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="デバッグモード: メール送信せず HTML をローカルファイルに出力。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ドライラン: 論文取得と表示のみ（要約・メール送信なし）。",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="詳細ログを出力する。",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="HTML 出力先ファイルパス（デバッグモード時）。",
    )
    return parser.parse_args()


def main() -> int:
    """メイン処理。終了コードを返す。"""
    args = parse_args()
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # ========== 設定読込 ==========
    logger.info("=" * 60)
    logger.info("PubMed 新着論文レポートシステム 起動")
    logger.info("=" * 60)

    config = Config.from_env()

    # コマンドライン引数で上書き
    keyword_ja = args.keyword if args.keyword else config.search_keywords
    days = args.days if args.days else config.search_days
    max_results = args.max_results if args.max_results else config.max_results
    debug_mode = args.debug or config.debug_mode

    # ========== バリデーション ==========
    search_errors = config.validate_for_search()
    if search_errors:
        for err in search_errors:
            logger.error(err)
        return 1

    # ========== キーワード変換 ==========
    logger.info("検索キーワード（日本語）: %s", keyword_ja)

    # Gemini クライアントをキーワード翻訳用に初期化（可能な場合）
    gemini_client_for_translate = None
    if config.gemini_api_key:
        try:
            from google import genai

            gemini_client_for_translate = genai.Client(api_key=config.gemini_api_key)
        except Exception:
            logger.warning("Gemini クライアントの初期化に失敗（翻訳）。辞書のみ使用します。")

    keyword_en = translate_keyword(
        keyword_ja, gemini_client_for_translate, config.gemini_model
    )
    logger.info("検索キーワード（英語）: %s", keyword_en)

    # ========== PubMed 検索 ==========
    logger.info("PubMed を検索中... (過去 %d 日間, 最大 %d 件)", days, max_results)
    articles = get_articles(keyword_en, config.entrez_email, days, max_results)

    if not articles:
        logger.warning("該当する論文が見つかりませんでした。処理を終了します。")
        return 0

    logger.info("%d 件の論文を取得しました。", len(articles))

    # ========== ドライラン ==========
    if args.dry_run:
        logger.info("--- ドライラン: 取得した論文一覧 ---")
        for i, art in enumerate(articles, 1):
            logger.info(
                "[%d] %s | %s | %s",
                i,
                art.get("title", "")[:80],
                art.get("journal", ""),
                art.get("pub_date", ""),
            )
        logger.info("ドライラン完了。")
        return 0

    # ========== メタデータ付与 ==========
    logger.info("メタデータを付与中（AI 要約 & IF）...")
    summary_warnings = config.validate_for_summary()
    for warn in summary_warnings:
        logger.warning(warn)

    articles = enrich_articles(
        articles,
        gemini_api_key=config.gemini_api_key,
        gemini_model_name=config.gemini_model,
    )

    # ========== HTML レポート生成 ==========
    logger.info("HTML レポートを生成中...")
    html_report = build_html_report(articles, keyword_ja, keyword_en)

    # ========== デバッグモード ==========
    if debug_mode:
        output_path = args.output or config.debug_output_file
        Path(output_path).write_text(html_report, encoding="utf-8")
        logger.info("デバッグ: HTML レポートを '%s' に出力しました。", output_path)
        logger.info("ブラウザで開いて内容を確認してください。")
        return 0

    # ========== メール送信 ==========
    email_errors = config.validate_for_email()
    if email_errors:
        for err in email_errors:
            logger.error(err)
        # メール送信できない場合でもHTMLは出力する
        fallback_path = "report_fallback.html"
        Path(fallback_path).write_text(html_report, encoding="utf-8")
        logger.info("メール設定不備のため HTML を '%s' に出力しました。", fallback_path)
        return 1

    logger.info("メールを送信中...")
    success = send_email(html_report, config, keyword_ja)

    if success:
        logger.info("✅ 処理が正常に完了しました。")
        return 0
    else:
        logger.error("❌ メール送信に失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

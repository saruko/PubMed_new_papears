"""メタデータ付与モジュール。

Gemini API による日本語要約と、ジャーナルインパクトファクター（IF）の付与を行う。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# プロジェクトルートからの相対パス
DEFAULT_IF_CSV = Path(__file__).resolve().parent / "data" / "journal_if.csv"


def load_impact_factors(csv_path: str | Path = DEFAULT_IF_CSV) -> dict[str, float]:
    """ジャーナル IF の CSV を読み込み、辞書として返す。

    Args:
        csv_path: journal_if.csv のパス

    Returns:
        {ジャーナル名(小文字): IF} の辞書
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning("IF データファイルが見つかりません: %s", csv_path)
        return {}

    try:
        df = pd.read_csv(csv_path)
        if_dict: dict[str, float] = {}
        for _, row in df.iterrows():
            name = str(row["journal_name"]).strip().lower()
            if_val = float(row["impact_factor"])
            if_dict[name] = if_val
        logger.info("IF データを %d 件読み込みました。", len(if_dict))
        return if_dict
    except Exception:
        logger.error("IF データの読み込みに失敗しました。", exc_info=True)
        return {}


def get_impact_factor(journal: str, if_dict: dict[str, float]) -> str:
    """ジャーナル名から IF を取得する。

    完全一致 → 部分一致の順で検索する。

    Args:
        journal: ジャーナル名
        if_dict: {ジャーナル名(小文字): IF} の辞書

    Returns:
        IF の文字列表現（見つからなければ "N/A"）
    """
    if not if_dict or not journal:
        return "N/A"

    journal_lower = journal.strip().lower()

    # 完全一致
    if journal_lower in if_dict:
        return f"{if_dict[journal_lower]:.1f}"

    # 部分一致（辞書キーがジャーナル名に含まれる、またはその逆）
    for key, value in if_dict.items():
        if key in journal_lower or journal_lower in key:
            return f"{value:.1f}"

    return "N/A"


def summarize_abstract(abstract: str, model, max_retries: int = 2) -> str:
    """Gemini API を使用して抄録を日本語で3行要約する。

    Args:
        abstract: 英語の抄録テキスト
        model: google.generativeai.GenerativeModel インスタンス
        max_retries: 失敗時のリトライ回数

    Returns:
        日本語の3行要約
    """
    if not abstract or not abstract.strip():
        return "抄録なし"

    prompt = (
        "あなたは医学論文の専門家です。以下の英語の論文抄録を、"
        "日本語で3行に要約してください。\n"
        "各行は「・」で始め、専門用語は正確に使用してください。\n"
        "出力は要約のみとし、それ以外の文は含めないでください。\n\n"
        f"抄録:\n{abstract}"
    )

    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(prompt)

            # セーフティフィルタでブロックされた場合の対応
            if response.candidates:
                candidate = response.candidates[0]
                # finish_reason が SAFETY の場合
                if hasattr(candidate, 'finish_reason') and candidate.finish_reason != 1:
                    reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                    logger.warning(
                        "Gemini 応答がブロックされました (finish_reason=%s)", reason
                    )
                    truncated = abstract[:200] + ("..." if len(abstract) > 200 else "")
                    return f"（セーフティフィルタにより要約不可）{truncated}"

                # parts から安全にテキストを取得
                if candidate.content and candidate.content.parts:
                    summary = candidate.content.parts[0].text.strip()
                    if summary:
                        logger.debug("要約生成完了（%d 文字）", len(summary))
                        return summary

            # response.text にフォールバック
            try:
                summary = response.text.strip()
                if summary:
                    logger.debug("要約生成完了（%d 文字）", len(summary))
                    return summary
            except (ValueError, AttributeError) as e:
                logger.warning("response.text の取得に失敗: %s", e)

            logger.warning("Gemini 応答が空でした（試行 %d/%d）", attempt + 1, max_retries + 1)

        except Exception as e:
            logger.warning(
                "AI 要約の生成に失敗（試行 %d/%d）: %s",
                attempt + 1,
                max_retries + 1,
                str(e),
                exc_info=True,
            )

        # リトライ前に待機
        if attempt < max_retries:
            wait = 2 * (attempt + 1)
            logger.info("  → %d 秒後にリトライします...", wait)
            time.sleep(wait)

    # 全リトライ失敗時のフォールバック
    truncated = abstract[:200] + ("..." if len(abstract) > 200 else "")
    return f"（要約失敗・原文抜粋）{truncated}"


def enrich_articles(
    articles: list[dict[str, Any]],
    gemini_api_key: str = "",
    gemini_model_name: str = "gemini-2.0-flash",
    if_csv_path: str | Path = DEFAULT_IF_CSV,
) -> list[dict[str, Any]]:
    """論文リストに IF と AI 要約を付与する。

    Args:
        articles: 論文情報の辞書リスト
        gemini_api_key: Gemini API キー（空文字列の場合は要約スキップ）
        gemini_model_name: 使用する Gemini モデル名
        if_csv_path: ジャーナル IF CSV のパス

    Returns:
        IF と要約が付与された論文リスト
    """
    # IF 辞書を読み込み
    if_dict = load_impact_factors(if_csv_path)

    # Gemini モデルを初期化
    model = None
    if gemini_api_key:
        try:
            import google.generativeai as genai
            from google.generativeai.types import HarmBlockThreshold, HarmCategory

            genai.configure(api_key=gemini_api_key)

            # 医学コンテンツがブロックされないようセーフティ設定を緩和
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            model = genai.GenerativeModel(
                gemini_model_name,
                safety_settings=safety_settings,
            )

            # テスト呼び出しで動作確認
            test_response = model.generate_content("Hello")
            test_text = test_response.text
            logger.info(
                "Gemini モデル '%s' の初期化・テスト成功（応答: %s）",
                gemini_model_name,
                test_text[:30] if test_text else "(空)",
            )
        except Exception as e:
            logger.error(
                "Gemini モデルの初期化/テストに失敗しました: %s", str(e), exc_info=True
            )
            model = None
    else:
        logger.warning(
            "GEMINI_API_KEY が未設定のため、AI 要約をスキップします。"
        )

    for i, article in enumerate(articles):
        # IF 付与
        article["impact_factor"] = get_impact_factor(
            article.get("journal", ""), if_dict
        )

        # AI 要約
        abstract = article.get("abstract", "")
        if model and abstract:
            article["summary_ja"] = summarize_abstract(abstract, model)
            # Gemini API レート制限対策（RPM を考慮して待機）
            if i < len(articles) - 1:
                time.sleep(4.0)
        else:
            if abstract:
                truncated = abstract[:200] + ("..." if len(abstract) > 200 else "")
                article["summary_ja"] = f"（AI要約なし）{truncated}"
            else:
                article["summary_ja"] = "抄録なし"

        logger.info(
            "[%d/%d] %s (IF: %s)",
            i + 1,
            len(articles),
            article.get("title", "")[:50],
            article["impact_factor"],
        )

    return articles

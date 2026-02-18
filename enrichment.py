"""メタデータ付与モジュール。

google.genai（新SDK）による日本語要約と、ジャーナルインパクトファクター（IF）の付与を行う。
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


# クォータ超過時のフォールバックモデル順序
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


def _get_fallback_models(primary_model: str) -> list[str]:
    """プライマリモデルを先頭にしたフォールバックリストを生成する。"""
    models = [primary_model]
    for m in FALLBACK_MODELS:
        if m not in models:
            models.append(m)
    return models


def summarize_abstract(
    abstract: str,
    client,
    model_name: str,
    fallback_models: list[str] | None = None,
    max_retries: int = 1,
) -> str:
    """Gemini API を使用して抄録を日本語で3行要約する。

    クォータ超過時は自動的にフォールバックモデルに切り替える。

    Args:
        abstract: 英語の抄録テキスト
        client: google.genai.Client インスタンス
        model_name: プライマリ Gemini モデル名
        fallback_models: フォールバックモデル名のリスト（None の場合は自動生成）
        max_retries: 各モデルでの失敗時のリトライ回数

    Returns:
        日本語の3行要約
    """
    if not abstract or not abstract.strip():
        return "抄録なし"

    from google.genai import types

    prompt = (
        "あなたは医学論文の専門家です。以下の英語の論文抄録を、"
        "日本語で3行に要約してください。\n"
        "各行は「・」で始め、専門用語は正確に使用してください。\n"
        "出力は要約のみとし、それ以外の文は含めないでください。\n\n"
        f"抄録:\n{abstract}"
    )

    # セーフティ設定（医学コンテンツがブロックされないよう緩和）
    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]

    models_to_try = fallback_models or _get_fallback_models(model_name)

    for model in models_to_try:
        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        safety_settings=safety_settings,
                    ),
                )

                if response.text:
                    summary = response.text.strip()
                    if summary:
                        logger.debug(
                            "要約生成完了（モデル: %s, %d 文字）", model, len(summary)
                        )
                        return summary

                logger.warning(
                    "Gemini 応答が空（モデル: %s, 試行 %d/%d）",
                    model, attempt + 1, max_retries + 1,
                )

            except Exception as e:
                error_msg = str(e)

                # クォータ超過 → 次のモデルにフォールバック
                if "429" in error_msg or "ResourceExhausted" in error_msg:
                    logger.warning(
                        "モデル '%s' のクォータ超過を検出。次のモデルに切り替えます。",
                        model,
                    )
                    break  # 内側ループを抜けて次のモデルへ

                logger.warning(
                    "AI 要約失敗（モデル: %s, 試行 %d/%d）: %s",
                    model, attempt + 1, max_retries + 1, error_msg,
                )

            # リトライ待機
            if attempt < max_retries:
                wait = 3 * (attempt + 1)
                logger.info("  → %d 秒後にリトライします...", wait)
                time.sleep(wait)
        else:
            # for ループが break せずに完了 = 全リトライ失敗（クォータ超過以外）
            continue
        # break で抜けた = クォータ超過 → 次のモデルへ continue
        continue

    # 全モデル・全リトライ失敗時のフォールバック
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

    # Gemini クライアントを初期化
    client = None
    active_model = gemini_model_name
    fallback_models = _get_fallback_models(gemini_model_name)

    if gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_api_key)

            # テスト呼び出しで動作確認（フォールバック付き）
            test_ok = False
            for model in fallback_models:
                try:
                    test_response = client.models.generate_content(
                        model=model,
                        contents="Say hello in one word.",
                    )
                    active_model = model
                    logger.info(
                        "Gemini モデル '%s' の初期化・テスト成功（応答: %s）",
                        model,
                        (test_response.text or "")[:30],
                    )
                    test_ok = True
                    break
                except Exception as e:
                    if "429" in str(e) or "ResourceExhausted" in str(e):
                        logger.warning(
                            "モデル '%s' はクォータ超過。次のモデルを試行します。", model
                        )
                        continue
                    raise  # 429 以外のエラーは再送出

            if not test_ok:
                logger.error("全モデルのクォータが超過しています。AI要約は利用できません。")
                client = None

        except Exception as e:
            logger.error(
                "Gemini の初期化/テストに失敗: %s", str(e), exc_info=True
            )
            client = None
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
        if client and abstract:
            article["summary_ja"] = summarize_abstract(
                abstract, client, active_model, fallback_models
            )
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

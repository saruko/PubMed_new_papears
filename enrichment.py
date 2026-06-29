"""メタデータ付与モジュール。

google.genai（新SDK）による日本語要約と、ジャーナルの2年平均被引用数
（インパクトファクター代用）の付与を行う。
被引用数は OpenAlex API から自動取得し、JSON ファイルにキャッシュする。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / "data" / "openalex_cache.json"


# ---------------------------------------------------------------------------
# OpenAlex API によるジャーナル被引用数取得
# ---------------------------------------------------------------------------

def load_openalex_cache(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, float | None]:
    """キャッシュファイルを読み込む。存在しなければ空辞書を返す。"""
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("キャッシュ読み込みに失敗しました: %s", cache_path)
    return {}


def save_openalex_cache(cache: dict[str, float | None], cache_path: Path = DEFAULT_CACHE_PATH) -> None:
    """キャッシュを JSON ファイルに保存する。"""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.warning("キャッシュ保存に失敗しました: %s", cache_path, exc_info=True)


def _fetch_openalex_citedness(journal: str) -> float | None:
    """OpenAlex API からジャーナルの2年平均被引用数を取得する。

    Args:
        journal: ジャーナル名

    Returns:
        2年平均被引用数（float）。取得失敗時は None。
    """
    # search= を使用（filter+select の組み合わせだと数字始まりフィールド名で400エラー）
    encoded = urllib.parse.quote(journal)
    url = f"https://api.openalex.org/sources?search={encoded}&per-page=1"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PubMedReporter/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        if results:
            # 2yr_mean_citedness は summary_stats の中に格納されている
            val = results[0].get("summary_stats", {}).get("2yr_mean_citedness")
            return float(val) if val is not None else None
    except Exception as e:
        logger.warning("OpenAlex API エラー (%s): %s", journal, e)
    return None


def get_impact_factor(
    journal: str,
    cache: dict[str, float | None],
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> str:
    """ジャーナル名から2年平均被引用数を取得する（キャッシュ優先）。

    Args:
        journal: ジャーナル名
        cache: {ジャーナル名(小文字): 被引用数 or None} のキャッシュ辞書
        cache_path: キャッシュファイルのパス

    Returns:
        被引用数の文字列（例: "5.3"）。取得できなければ "N/A"。
    """
    if not journal:
        return "N/A"

    key = journal.strip().lower()

    if key not in cache:
        logger.debug("OpenAlex API 問い合わせ: %s", journal)
        val = _fetch_openalex_citedness(journal)
        cache[key] = val
        save_openalex_cache(cache, cache_path)
        # API レート制限を避けるため短時間待機
        time.sleep(0.5)

    val = cache[key]
    return f"{val:.1f}" if val is not None else "N/A"


# ---------------------------------------------------------------------------
# Gemini AI 要約
# ---------------------------------------------------------------------------

# フォールバックモデル順序
FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
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

            if attempt < max_retries:
                wait = 3 * (attempt + 1)
                logger.info("  → %d 秒後にリトライします...", wait)
                time.sleep(wait)

    truncated = abstract[:200] + ("..." if len(abstract) > 200 else "")
    return f"（要約失敗・原文抜粋）{truncated}"


# ---------------------------------------------------------------------------
# メインのエンリッチメント関数
# ---------------------------------------------------------------------------

def enrich_articles(
    articles: list[dict[str, Any]],
    gemini_api_key: str = "",
    gemini_model_name: str = "gemini-3.1-flash-lite",
    cache_path: str | Path = DEFAULT_CACHE_PATH,
) -> list[dict[str, Any]]:
    """論文リストに2年平均被引用数と AI 要約を付与する。

    Args:
        articles: 論文情報の辞書リスト
        gemini_api_key: Gemini API キー（空文字列の場合は要約スキップ）
        gemini_model_name: 使用する Gemini モデル名
        cache_path: OpenAlex キャッシュファイルのパス

    Returns:
        被引用数と要約が付与された論文リスト
    """
    cache_path = Path(cache_path)
    openalex_cache = load_openalex_cache(cache_path)

    client = None
    fallback_models = _get_fallback_models(gemini_model_name)
    active_model = fallback_models[0]

    if gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_api_key)

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
                    raise

            if not test_ok:
                logger.error("全モデルのクォータが超過しています。AI要約は利用できません。")
                client = None

        except Exception as e:
            logger.error("Gemini の初期化/テストに失敗: %s", str(e), exc_info=True)
            client = None
    else:
        logger.warning("GEMINI_API_KEY が未設定のため、AI 要約をスキップします。")

    for i, article in enumerate(articles):
        # 2年平均被引用数を付与
        article["impact_factor"] = get_impact_factor(
            article.get("journal", ""), openalex_cache, cache_path
        )

        # AI 要約
        abstract = article.get("abstract", "")
        if client and abstract:
            article["summary_ja"] = summarize_abstract(
                abstract, client, active_model, fallback_models
            )
            if i < len(articles) - 1:
                time.sleep(4.0)
        else:
            if abstract:
                truncated = abstract[:200] + ("..." if len(abstract) > 200 else "")
                article["summary_ja"] = f"（AI要約なし）{truncated}"
            else:
                article["summary_ja"] = "抄録なし"

        logger.info(
            "[%d/%d] %s (2yr被引用数: %s)",
            i + 1,
            len(articles),
            article.get("title", "")[:50],
            article["impact_factor"],
        )

    return articles

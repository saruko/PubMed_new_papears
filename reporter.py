"""レポート生成 & メール送信モジュール。

論文情報から HTML レポートを生成し、SMTP 経由で送信する。
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from config import Config

logger = logging.getLogger(__name__)


def build_html_report(
    articles: list[dict[str, Any]],
    keyword_ja: str,
    keyword_en: str,
) -> str:
    """論文リストから HTML メールレポートを生成する。

    IF 降順でソートした論文テーブルを含む、モダンなHTMLを出力。

    Args:
        articles: メタデータ付与済み論文リスト
        keyword_ja: 日本語キーワード
        keyword_en: 英語キーワード

    Returns:
        HTML 文字列
    """
    # IF 降順ソート（N/A は末尾）
    def sort_key(a: dict) -> float:
        try:
            return -float(a.get("impact_factor", 0))
        except (ValueError, TypeError):
            return 0.0

    sorted_articles = sorted(articles, key=sort_key)

    today = datetime.now().strftime("%Y年%m月%d日")
    article_count = len(sorted_articles)

    # 各論文の HTML 行を生成
    rows_html = ""
    for i, art in enumerate(sorted_articles, 1):
        summary_html = art.get("summary_ja", "").replace("\n", "<br>")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding: 16px; vertical-align: top;">
                <div style="margin-bottom: 8px;">
                    <span style="
                        background: #1a73e8;
                        color: white;
                        padding: 2px 8px;
                        border-radius: 12px;
                        font-size: 12px;
                        font-weight: bold;
                    ">{i}</span>
                    <span style="
                        background: {_if_badge_color(art.get('impact_factor', 'N/A'))};
                        color: white;
                        padding: 2px 8px;
                        border-radius: 12px;
                        font-size: 12px;
                        margin-left: 4px;
                    ">2yr被引用数: {art.get("impact_factor", "N/A")}</span>
                </div>
                <a href="{art.get('url', '#')}" style="
                    color: #1a0dab;
                    text-decoration: none;
                    font-size: 16px;
                    font-weight: bold;
                    line-height: 1.4;
                ">{art.get("title", "No Title")}</a>
                <div style="
                    color: #5f6368;
                    font-size: 13px;
                    margin-top: 4px;
                ">{art.get("authors", "")}</div>
                <div style="
                    color: #188038;
                    font-size: 13px;
                    margin-top: 2px;
                ">{art.get("journal", "")} | {art.get("pub_date", "")}</div>
                <div style="
                    background: #f8f9fa;
                    border-left: 3px solid #1a73e8;
                    padding: 10px 14px;
                    margin-top: 10px;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                ">{summary_html}</div>
            </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="
    margin: 0;
    padding: 0;
    background-color: #f5f5f5;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
">
    <div style="
        max-width: 700px;
        margin: 20px auto;
        background: white;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    ">
        <!-- ヘッダー -->
        <div style="
            background: linear-gradient(135deg, #1a73e8, #0d47a1);
            color: white;
            padding: 24px 30px;
        ">
            <h1 style="margin: 0; font-size: 22px; font-weight: 600;">
                📚 PubMed 新着論文レポート
            </h1>
            <p style="margin: 8px 0 0; font-size: 14px; opacity: 0.9;">
                {today} ｜ キーワード: {keyword_ja}（{keyword_en}）｜ {article_count} 件
            </p>
        </div>

        <!-- 論文リスト -->
        <table style="
            width: 100%;
            border-collapse: collapse;
        ">
            {rows_html}
        </table>

        <!-- フッター -->
        <div style="
            background: #f8f9fa;
            padding: 16px 30px;
            text-align: center;
            font-size: 12px;
            color: #999;
        ">
            このレポートは PubMed API + Gemini AI により自動生成されています。<br>
            被引用数は OpenAlex API から取得した2年平均値です（参考値）。
        </div>
    </div>
</body>
</html>"""

    return html


def _if_badge_color(if_value: str) -> str:
    """IF 値に応じたバッジ色を返す。"""
    try:
        val = float(if_value)
        if val >= 10:
            return "#d93025"  # 赤（高IF）
        if val >= 5:
            return "#e37400"  # オレンジ
        if val >= 2:
            return "#188038"  # 緑
        return "#5f6368"  # グレー
    except (ValueError, TypeError):
        return "#9aa0a6"  # N/A 用


def send_email(html_content: str, config: Config, keyword_ja: str) -> bool:
    """HTML レポートをメールで送信する。

    Args:
        html_content: HTML 形式のメール本文
        config: アプリケーション設定
        keyword_ja: 件名に含める日本語キーワード

    Returns:
        送信成功なら True
    """
    today = datetime.now().strftime("%Y/%m/%d")
    subject = f"📚 PubMed 新着論文レポート [{keyword_ja}] {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.smtp_user
    msg["To"] = ", ".join(config.recipient_emails)

    # プレーンテキスト版（フォールバック）
    plain_text = (
        f"PubMed 新着論文レポート ({keyword_ja}) - {today}\n\n"
        "このメールは HTML 形式です。HTML 対応のメールクライアントでご覧ください。"
    )
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.smtp_user, config.smtp_password)
            server.sendmail(
                config.smtp_user,
                config.recipient_emails,
                msg.as_string(),
            )
        logger.info(
            "メールを送信しました → %s", ", ".join(config.recipient_emails)
        )
        return True
    except Exception:
        logger.error("メール送信に失敗しました。", exc_info=True)
        return False

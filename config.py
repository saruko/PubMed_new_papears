"""設定管理モジュール。

.env ファイルまたは環境変数（GitHub Actions Secrets 等）から
アプリケーション設定を読み込む。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# プロジェクトルートの .env を読み込む（存在しなくてもエラーにならない）
load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass
class Config:
    """アプリケーション設定を保持するデータクラス。"""

    # --- Gemini API ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"

    # --- PubMed ---
    entrez_email: str = ""

    # --- 検索 ---
    search_keywords: str = "眼科"
    search_days: int = 7
    max_results: int = 50

    # --- SMTP ---
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # --- 送信先（複数対応） ---
    recipient_emails: list[str] = field(default_factory=list)

    # --- デバッグ ---
    debug_mode: bool = False
    debug_output_file: str = "debug_report.html"

    @classmethod
    def from_env(cls) -> "Config":
        """環境変数から Config を生成する。"""
        recipients_raw = os.getenv("RECIPIENT_EMAILS", "")
        recipients = [
            e.strip() for e in recipients_raw.split(",") if e.strip()
        ]

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            entrez_email=os.getenv("ENTREZ_EMAIL", ""),
            search_keywords=os.getenv("SEARCH_KEYWORDS", "眼科"),
            search_days=int(os.getenv("SEARCH_DAYS", "7")),
            max_results=int(os.getenv("MAX_RESULTS", "50")),
            smtp_server=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            recipient_emails=recipients,
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
            debug_output_file=os.getenv("DEBUG_OUTPUT_FILE", "debug_report.html"),
        )

    # ---- バリデーション ----

    def validate_for_search(self) -> list[str]:
        """PubMed 検索に必要な設定を検証する。"""
        errors: list[str] = []
        if not self.entrez_email:
            errors.append("ENTREZ_EMAIL が未設定です。")
        return errors

    def validate_for_summary(self) -> list[str]:
        """AI 要約に必要な設定を検証する。"""
        errors: list[str] = []
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY が未設定です（要約をスキップします）。")
        return errors

    def validate_for_email(self) -> list[str]:
        """メール送信に必要な設定を検証する。"""
        errors: list[str] = []
        if not self.smtp_user:
            errors.append("SMTP_USER が未設定です。")
        if not self.smtp_password:
            errors.append("SMTP_PASSWORD が未設定です。")
        if not self.recipient_emails:
            errors.append("RECIPIENT_EMAILS が未設定です。")
        return errors

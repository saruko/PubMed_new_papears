"""ユニットテスト — PubMed 新着論文レポートシステム。

モックを使用して外部 API に依存しないテストを実施する。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# テスト対象モジュール
from config import Config
from enrichment import _get_fallback_models, get_impact_factor, load_impact_factors
from keyword_translator import KEYWORD_MAP, translate_keyword
from reporter import build_html_report


# ============================================================
# Config テスト
# ============================================================


class TestConfig:
    """Config データクラスのテスト。"""

    def test_from_env_defaults(self):
        """環境変数未設定時のデフォルト値。"""
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()
            assert config.search_keywords == "眼科"
            assert config.search_days == 7
            assert config.max_results == 50
            assert config.smtp_port == 587
            assert config.debug_mode is False
            assert config.recipient_emails == []

    def test_from_env_with_values(self):
        """環境変数設定時の値。"""
        env = {
            "GEMINI_API_KEY": "test-key",
            "ENTREZ_EMAIL": "test@example.com",
            "RECIPIENT_EMAILS": "a@b.com, c@d.com",
            "SEARCH_DAYS": "14",
            "DEBUG_MODE": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.from_env()
            assert config.gemini_api_key == "test-key"
            assert config.entrez_email == "test@example.com"
            assert config.recipient_emails == ["a@b.com", "c@d.com"]
            assert config.search_days == 14
            assert config.debug_mode is True

    def test_validate_for_search(self):
        """検索バリデーション。"""
        config = Config(entrez_email="")
        errors = config.validate_for_search()
        assert len(errors) == 1
        assert "ENTREZ_EMAIL" in errors[0]

        config = Config(entrez_email="test@example.com")
        assert config.validate_for_search() == []

    def test_validate_for_email(self):
        """メールバリデーション。"""
        config = Config(smtp_user="", smtp_password="", recipient_emails=[])
        errors = config.validate_for_email()
        assert len(errors) == 3


# ============================================================
# keyword_translator テスト
# ============================================================


class TestKeywordTranslator:
    """キーワード変換のテスト。"""

    def test_ascii_passthrough(self):
        """英語キーワードはそのまま返す。"""
        assert translate_keyword("glaucoma") == "glaucoma"
        assert translate_keyword("ophthalmology") == "ophthalmology"

    def test_dictionary_lookup(self):
        """組込み辞書での変換。"""
        assert translate_keyword("眼科") == "ophthalmology"
        assert translate_keyword("緑内障") == "glaucoma"
        assert translate_keyword("白内障") == "cataract"
        assert translate_keyword("糖尿病網膜症") == "diabetic retinopathy"

    def test_dictionary_completeness(self):
        """主要な眼科用語が辞書に含まれている。"""
        essential_terms = ["眼科", "緑内障", "白内障", "網膜", "角膜", "黄斑変性"]
        for term in essential_terms:
            assert term in KEYWORD_MAP, f"'{term}' が辞書にありません"

    def test_unknown_keyword_without_gemini(self):
        """辞書にない用語（Gemini なし）はそのまま返す。"""
        result = translate_keyword("未知の用語テスト", gemini_client=None)
        assert result == "未知の用語テスト"


# ============================================================
# enrichment テスト
# ============================================================


class TestEnrichment:
    """メタデータ付与のテスト。"""

    def test_load_impact_factors(self):
        """IF CSV の読み込み。"""
        csv_path = Path(__file__).resolve().parent.parent / "data" / "journal_if.csv"
        if csv_path.exists():
            if_dict = load_impact_factors(csv_path)
            assert len(if_dict) > 0
            # 主要ジャーナルが含まれているか
            assert "ophthalmology" in if_dict
            assert if_dict["ophthalmology"] > 0

    def test_load_impact_factors_missing_file(self):
        """存在しないファイルの場合は空辞書。"""
        if_dict = load_impact_factors("/nonexistent/path.csv")
        assert if_dict == {}

    def test_get_fallback_models(self):
        """フォールバックモデルの生成ロジックをテスト。"""
        # 2.5系の場合はそのまま先頭
        models_25 = _get_fallback_models("gemini-2.5-flash")
        assert models_25[0] == "gemini-2.5-flash"

        # 2.0系の場合は警告が出つつ、2.5系が優先される（リストに含まれる）
        models_20 = _get_fallback_models("gemini-2.0-flash")
        assert "gemini-2.0-flash" not in models_20 # 除外されているはず
        assert "gemini-2.5-flash" in models_20
        assert models_20[0] == "gemini-2.5-flash"

    def test_get_impact_factor_exact(self):
        """完全一致でのIF検索。"""
        if_dict = {"ophthalmology": 13.7, "retina": 3.2}
        assert get_impact_factor("Ophthalmology", if_dict) == "13.7"
        assert get_impact_factor("Retina", if_dict) == "3.2"

    def test_get_impact_factor_partial(self):
        """部分一致でのIF検索。"""
        if_dict = {"british journal of ophthalmology": 4.1}
        result = get_impact_factor(
            "The British Journal of Ophthalmology", if_dict
        )
        assert result == "4.1"

    def test_get_impact_factor_not_found(self):
        """見つからない場合は N/A。"""
        if_dict = {"ophthalmology": 13.7}
        assert get_impact_factor("Unknown Journal", if_dict) == "N/A"

    def test_get_impact_factor_empty(self):
        """空辞書の場合は N/A。"""
        assert get_impact_factor("Ophthalmology", {}) == "N/A"


# ============================================================
# reporter テスト
# ============================================================


class TestReporter:
    """レポート生成のテスト。"""

    def _sample_articles(self) -> list[dict]:
        return [
            {
                "pmid": "12345678",
                "title": "Test Article Title",
                "abstract": "Test abstract content.",
                "authors": "Tanaka A, Suzuki B",
                "journal": "Ophthalmology",
                "pub_date": "2026 Feb",
                "doi": "10.1234/test",
                "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "impact_factor": "13.7",
                "summary_ja": "・テスト要約1行目\n・テスト要約2行目\n・テスト要約3行目",
            },
            {
                "pmid": "87654321",
                "title": "Another Test Article",
                "abstract": "Another abstract.",
                "authors": "Smith C",
                "journal": "Retina",
                "pub_date": "2026 Feb",
                "doi": "",
                "url": "https://pubmed.ncbi.nlm.nih.gov/87654321/",
                "impact_factor": "3.2",
                "summary_ja": "・別の要約",
            },
        ]

    def test_build_html_report_contains_articles(self):
        """HTMLレポートに論文情報が含まれている。"""
        articles = self._sample_articles()
        html = build_html_report(articles, "眼科", "ophthalmology")

        assert "Test Article Title" in html
        assert "Another Test Article" in html
        assert "Ophthalmology" in html
        assert "13.7" in html
        assert "3.2" in html
        assert "pubmed.ncbi.nlm.nih.gov" in html

    def test_build_html_report_header(self):
        """HTMLレポートにヘッダー情報が含まれている。"""
        articles = self._sample_articles()
        html = build_html_report(articles, "眼科", "ophthalmology")

        assert "PubMed 新着論文レポート" in html
        assert "眼科" in html
        assert "2 件" in html

    def test_build_html_report_sorted_by_if(self):
        """IF降順でソートされている。"""
        articles = self._sample_articles()
        html = build_html_report(articles, "眼科", "ophthalmology")

        # IF 13.7 の論文が IF 3.2 より先に出現するか
        pos_high = html.index("13.7")
        pos_low = html.index("3.2")
        assert pos_high < pos_low

    def test_build_html_report_empty(self):
        """空リストでもエラーにならない。"""
        html = build_html_report([], "眼科", "ophthalmology")
        assert "PubMed 新着論文レポート" in html
        assert "0 件" in html

    def test_build_html_valid_html(self):
        """出力が有効なHTMLである。"""
        articles = self._sample_articles()
        html = build_html_report(articles, "眼科", "ophthalmology")

        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<body" in html


# ============================================================
# pubmed_fetcher テスト（モック）
# ============================================================


class TestPubmedFetcher:
    """PubMed データ収集のテスト（モック使用）。"""

    @patch("pubmed_fetcher.Entrez")
    def test_search_pubmed_returns_ids(self, mock_entrez):
        """PubMed 検索が PMID リストを返す。"""
        from pubmed_fetcher import search_pubmed

        mock_handle = MagicMock()
        mock_entrez.esearch.return_value = mock_handle
        mock_entrez.read.return_value = {
            "Count": "2",
            "IdList": ["11111111", "22222222"],
        }

        result = search_pubmed("ophthalmology", "test@example.com", days=7)
        assert result == ["11111111", "22222222"]
        mock_entrez.esearch.assert_called_once()

    @patch("pubmed_fetcher.Entrez")
    def test_search_pubmed_empty(self, mock_entrez):
        """検索結果なしの場合。"""
        from pubmed_fetcher import search_pubmed

        mock_handle = MagicMock()
        mock_entrez.esearch.return_value = mock_handle
        mock_entrez.read.return_value = {"Count": "0", "IdList": []}

        result = search_pubmed("obscure_keyword", "test@example.com")
        assert result == []

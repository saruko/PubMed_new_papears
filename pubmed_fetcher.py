"""PubMed からの論文データ収集モジュール。

Biopython の Entrez API を使用して、指定キーワードの
最新論文を検索・取得する。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from Bio import Entrez

logger = logging.getLogger(__name__)


def search_pubmed(
    keyword: str,
    email: str,
    days: int = 7,
    max_results: int = 50,
) -> list[str]:
    """PubMed を検索し、PMID のリストを返す。

    Args:
        keyword: 英語の検索キーワード
        email: NCBI に通知するメールアドレス
        days: 過去何日分を検索するか
        max_results: 最大取得件数

    Returns:
        PMID のリスト
    """
    Entrez.email = email

    # 日付範囲を構築
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    date_range = (
        f'("{start_date.strftime("%Y/%m/%d")}"[PDAT] : '
        f'"{end_date.strftime("%Y/%m/%d")}"[PDAT])'
    )
    query = f"{keyword} AND {date_range}"

    logger.info("PubMed 検索クエリ: %s", query)

    try:
        handle = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=max_results,
            sort="pub_date",
        )
        results = Entrez.read(handle)
        handle.close()

        pmid_list: list[str] = results.get("IdList", [])
        count = results.get("Count", "0")
        logger.info("検索結果: %s 件中 %d 件を取得", count, len(pmid_list))
        return pmid_list

    except Exception:
        logger.error("PubMed 検索に失敗しました。", exc_info=True)
        return []


def fetch_details(pmid_list: list[str], email: str) -> list[dict[str, Any]]:
    """PMID リストから論文の詳細情報を取得する。

    Args:
        pmid_list: PMID のリスト
        email: NCBI に通知するメールアドレス

    Returns:
        論文情報の辞書リスト
    """
    if not pmid_list:
        return []

    Entrez.email = email
    articles: list[dict[str, Any]] = []

    # バッチ処理（一度に最大 200 件）
    batch_size = 200
    for start in range(0, len(pmid_list), batch_size):
        batch = pmid_list[start : start + batch_size]
        ids = ",".join(batch)

        try:
            handle = Entrez.efetch(
                db="pubmed",
                id=ids,
                rettype="xml",
                retmode="xml",
            )
            records = Entrez.read(handle)
            handle.close()
        except Exception:
            logger.error(
                "PubMed 詳細取得に失敗しました（batch %d）。",
                start,
                exc_info=True,
            )
            continue

        for article_data in records.get("PubmedArticle", []):
            article = _parse_article(article_data)
            if article:
                articles.append(article)

        # レート制限を遵守（3 req/sec）
        time.sleep(0.4)

    logger.info("論文詳細を %d 件取得しました。", len(articles))
    return articles


def _parse_article(article_data: dict) -> dict[str, Any] | None:
    """PubMed XML のレコードをパースして辞書に変換する。"""
    try:
        medline = article_data.get("MedlineCitation", {})
        pmid = str(medline.get("PMID", ""))
        article = medline.get("Article", {})

        # タイトル
        title = str(article.get("ArticleTitle", "No Title"))

        # 抄録
        abstract_parts = article.get("Abstract", {}).get("AbstractText", [])
        abstract = " ".join(str(part) for part in abstract_parts) if abstract_parts else ""

        # 著者
        author_list = article.get("AuthorList", [])
        authors = []
        for author in author_list:
            last_name = author.get("LastName", "")
            fore_name = author.get("ForeName", "")
            if last_name:
                authors.append(f"{last_name} {fore_name}".strip())
        authors_str = ", ".join(authors[:5])  # 最大5名
        if len(author_list) > 5:
            authors_str += " et al."

        # ジャーナル
        journal_info = article.get("Journal", {})
        journal = str(journal_info.get("Title", "Unknown Journal"))

        # 出版日
        pub_date_info = journal_info.get("JournalIssue", {}).get("PubDate", {})
        year = pub_date_info.get("Year", "")
        month = pub_date_info.get("Month", "")
        day = pub_date_info.get("Day", "")
        pub_date = " ".join(filter(None, [year, month, day]))

        # DOI
        doi = ""
        id_list = article.get("ELocationID", [])
        for eid in id_list:
            if str(eid.attributes.get("EIdType", "")) == "doi":
                doi = str(eid)
                break

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors_str,
            "journal": journal,
            "pub_date": pub_date,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
    except Exception:
        logger.warning("論文レコードのパースに失敗しました。", exc_info=True)
        return None


def get_articles(
    keyword: str,
    email: str,
    days: int = 7,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """キーワードで PubMed を検索し、論文情報のリストを返すファサード関数。

    Args:
        keyword: 英語の検索キーワード
        email: NCBI に通知するメールアドレス
        days: 過去何日分を検索するか
        max_results: 最大取得件数

    Returns:
        論文情報の辞書リスト
    """
    pmids = search_pubmed(keyword, email, days, max_results)
    if not pmids:
        logger.warning("該当する論文が見つかりませんでした。")
        return []

    return fetch_details(pmids, email)

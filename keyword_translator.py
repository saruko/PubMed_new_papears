"""日本語キーワードを PubMed 検索用の英語医学用語に変換するモジュール。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 眼科分野を中心とした日本語→英語医学用語マッピング
KEYWORD_MAP: dict[str, str] = {
    # 診療科
    "眼科": "ophthalmology",
    "眼科学": "ophthalmology",
    # 疾患
    "緑内障": "glaucoma",
    "白内障": "cataract",
    "加齢黄斑変性": "age-related macular degeneration",
    "黄斑変性": "macular degeneration",
    "糖尿病網膜症": "diabetic retinopathy",
    "網膜剥離": "retinal detachment",
    "網膜色素変性": "retinitis pigmentosa",
    "ぶどう膜炎": "uveitis",
    "ドライアイ": "dry eye disease",
    "角膜炎": "keratitis",
    "結膜炎": "conjunctivitis",
    "斜視": "strabismus",
    "弱視": "amblyopia",
    "近視": "myopia",
    "遠視": "hyperopia",
    "乱視": "astigmatism",
    "老視": "presbyopia",
    "円錐角膜": "keratoconus",
    "翼状片": "pterygium",
    "眼瞼下垂": "ptosis",
    "視神経炎": "optic neuritis",
    "網膜静脈閉塞症": "retinal vein occlusion",
    "網膜動脈閉塞症": "retinal artery occlusion",
    "黄斑浮腫": "macular edema",
    "黄斑円孔": "macular hole",
    "網膜前膜": "epiretinal membrane",
    "硝子体出血": "vitreous hemorrhage",
    "眼内炎": "endophthalmitis",
    "視野欠損": "visual field defect",
    # 解剖
    "網膜": "retina",
    "角膜": "cornea",
    "水晶体": "lens",
    "硝子体": "vitreous",
    "視神経": "optic nerve",
    "虹彩": "iris",
    "強膜": "sclera",
    "脈絡膜": "choroid",
    "結膜": "conjunctiva",
    "黄斑": "macula",
    "眼瞼": "eyelid",
    "涙腺": "lacrimal gland",
    # 手技・治療
    "硝子体手術": "vitrectomy",
    "レーシック": "LASIK",
    "眼内レンズ": "intraocular lens",
    "光凝固": "photocoagulation",
    "抗VEGF": "anti-VEGF",
    "角膜移植": "corneal transplantation",
    "ICL": "implantable collamer lens",
    # 検査
    "OCT": "optical coherence tomography",
    "眼圧": "intraocular pressure",
    "視力": "visual acuity",
    "蛍光眼底造影": "fluorescein angiography",
    "眼底検査": "fundoscopy",
    # 一般医学
    "糖尿病": "diabetes mellitus",
    "高血圧": "hypertension",
    "人工知能": "artificial intelligence",
    "機械学習": "machine learning",
    "深層学習": "deep learning",
    "臨床試験": "clinical trial",
    "メタ解析": "meta-analysis",
    "疫学": "epidemiology",
}


def translate_keyword(
    jp_keyword: str, gemini_client=None, gemini_model_name: str = "gemini-2.5-flash"
) -> str:
    """日本語キーワードを英語医学用語に変換する。

    1. 組込み辞書を検索
    2. 辞書にない場合、Gemini API で翻訳（利用可能な場合）
    3. どちらも使えない場合、元のキーワードをそのまま返す

    Args:
        jp_keyword: 日本語キーワード
        gemini_client: google.genai.Client インスタンス（任意）
        gemini_model_name: 使用する Gemini モデル名

    Returns:
        英語の医学用語
    """
    keyword = jp_keyword.strip()

    # ASCII のみなら既に英語とみなす
    if keyword.isascii():
        logger.info("キーワード '%s' は既に英語です。変換をスキップします。", keyword)
        return keyword

    # 組込み辞書で検索
    if keyword in KEYWORD_MAP:
        translated = KEYWORD_MAP[keyword]
        logger.info("辞書変換: '%s' → '%s'", keyword, translated)
        return translated

    # Gemini API で翻訳
    if gemini_client is not None:
        try:
            prompt = (
                f"以下の日本語の医学用語を、PubMedで検索するための"
                f"正確な英語の医学用語に変換してください。\n"
                f"英語の医学用語のみを出力し、それ以外は何も出力しないでください。\n\n"
                f"日本語: {keyword}"
            )
            response = gemini_client.models.generate_content(
                model=gemini_model_name,
                contents=prompt,
            )
            translated = response.text.strip()
            logger.info("Gemini 翻訳: '%s' → '%s'", keyword, translated)
            return translated
        except Exception:
            logger.warning(
                "Gemini API による翻訳に失敗しました。元のキーワードを使用します。",
                exc_info=True,
            )

    logger.warning(
        "キーワード '%s' の変換ができませんでした。そのまま使用します。", keyword
    )
    return keyword

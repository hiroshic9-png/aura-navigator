"""
AURA MVP — テキスト正規化ユーティリティ

検索クエリおよびDBデータのUnicode正規化を担当。
全角英数字→半角、半角カタカナ→全角、などの変換を行い、
検索ヒット率を向上させる。
"""

import unicodedata


def normalize_query(text: str) -> str:
    """
    検索クエリをNFKC正規化する

    変換例:
    - 全角英字「Ａ」→半角「A」
    - 全角数字「１２３」→半角「123」
    - 半角カタカナ「ｱｲｳ」→全角「アイウ」
    - 全角スペース「　」→半角スペース「 」
    - 連続空白の圧縮

    Args:
        text: 正規化対象の文字列

    Returns:
        NFKC正規化済みの文字列
    """
    if not text:
        return text
    # NFKC正規化（Unicode互換分解→正規合成）
    normalized = unicodedata.normalize("NFKC", text)
    # 全角スペースを半角に変換（NFKCでは変換されない場合がある）
    normalized = normalized.replace("\u3000", " ")
    # 連続空白を1つに圧縮
    normalized = " ".join(normalized.split())
    return normalized.strip()

"""文本预处理：清洗、敏感词过滤、长文本分段。"""
from __future__ import annotations

import re

# 分段时优先在这些标点后切开
_SENTENCE_ENDS = "。！？；…!?;\n"


def normalize(text: str) -> str:
    """去掉多余空行与首尾空白，统一换行符。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)          # 行尾空格
    text = re.sub(r"\n{3,}", "\n\n", text)          # 连续空行压成一个
    text = re.sub(r"[ \t]{2,}", " ", text)          # 连续空格
    return text.strip()


def filter_sensitive(text: str, words: list[str]) -> tuple[str, list[str]]:
    """命中敏感词时用 * 遮蔽，返回 (处理后文本, 命中词列表)。

    不直接拒绝整段文本——长文里出现一个敏感词就全废体验太差，
    改成遮蔽 + 记录，管理员可在日志里看到。
    """
    hits: list[str] = []
    for word in words:
        if not word:
            continue
        if word in text:
            hits.append(word)
            text = text.replace(word, "*" * len(word))
    return text, hits


def split_chunks(text: str, max_len: int = 280) -> list[str]:
    """把长文本切成不超过 max_len 的片段。

    策略：先按段落切，段落仍超长则按句末标点切，最后兜底按长度硬切。
    这样每一段都是完整句子，拼接后听起来才自然。
    """
    text = normalize(text)
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_len:
            chunks.append(paragraph)
            continue
        # 按句末标点切句，保留标点
        buf = ""
        for ch in paragraph:
            buf += ch
            if ch in _SENTENCE_ENDS and len(buf) >= max_len * 0.55:
                chunks.append(buf.strip())
                buf = ""
        if buf.strip():
            chunks.append(buf.strip())

    # 兜底：仍然超长的片段硬切
    final: list[str] = []
    for c in chunks:
        while len(c) > max_len:
            final.append(c[:max_len])
            c = c[max_len:]
        if c:
            final.append(c)
    return final

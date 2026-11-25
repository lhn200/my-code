from __future__ import annotations

import pytest

from app.memory.digest import (
    JD_DIGEST_LIMIT,
    RESUME_DIGEST_LIMIT,
    DigestError,
    build_jd_digest,
    build_resume_digest,
    digest_meta,
)


def test_short_texts_are_returned_unchanged() -> None:
    jd = "负责后端开发。熟悉 Python。"
    resume = "技能：Python、FastAPI"

    jd_digest = build_jd_digest(jd)
    resume_digest = build_resume_digest(resume)

    assert jd_digest.text == jd
    assert jd_digest.truncated is False
    assert jd_digest.fallback is False
    assert jd_digest.omitted_chars == 0
    assert resume_digest.text == resume
    assert resume_digest.truncated is False


def test_long_jd_keeps_responsibilities_requirements_and_keywords() -> None:
    responsibilities = "".join(
        f"负责交易系统模块{index}的设计与开发。" for index in range(30)
    )
    requirements = "".join(
        f"任职要求{index}：熟悉 Python 与 FastAPI，本科以上学历，5 年以上经验。"
        for index in range(30)
    )
    jd = f"岗位职责：{responsibilities}\n{requirements}\n关键词：Python FastAPI SQLite 高并发 微服务"

    digest = build_jd_digest(jd)

    assert len(jd) > JD_DIGEST_LIMIT
    assert len(digest.text) <= JD_DIGEST_LIMIT
    assert "【职责】" in digest.text
    assert "【硬性要求】" in digest.text
    assert "【关键词】" in digest.text
    assert "Python" in digest.text
    assert digest.fallback is False
    assert digest.truncated is True
    assert digest.original_chars == len(jd)


def test_jd_digest_prefers_structured_profile() -> None:
    profile = {
        "responsibilities": ["负责核心交易系统"],
        "must_have": ["5 年以上 Python 经验"],
        "keywords": ["Python", "FastAPI"],
    }

    digest = build_jd_digest("无关长文本。" * 200, profile=profile)

    assert digest.text == (
        "【职责】负责核心交易系统\n"
        "【硬性要求】5 年以上 Python 经验\n"
        "【关键词】Python；FastAPI"
    )
    assert digest.fallback is False


def test_long_resume_keeps_skills_experience_and_metrics() -> None:
    lines = [
        "技能：Python、FastAPI、SQLite、Docker、Kubernetes",
        "工作经历：在 ABC 公司负责后端服务开发，接口性能提升 40%",
        "项目经历：主导订单系统重构，服务 200 万用户",
        "教育：本科，计算机科学与技术",
    ]
    lines.extend(
        f"工作经历第{index}段：负责订单链路优化，延迟下降 {index}%，服务 {index}00 万请求。"
        for index in range(40)
    )
    resume = "\n".join(lines)

    digest = build_resume_digest(resume)

    assert len(resume) > RESUME_DIGEST_LIMIT
    assert len(digest.text) <= RESUME_DIGEST_LIMIT
    assert "【技能】" in digest.text
    assert "Python" in digest.text
    assert "【工作经历】" in digest.text
    assert "40%" in digest.text
    assert digest.fallback is False
    assert digest.truncated is True


def test_jd_falls_back_with_marker_when_no_structure() -> None:
    digest = build_jd_digest("甲" * 3000)

    assert len(digest.text) <= JD_DIGEST_LIMIT
    assert digest.fallback is True
    assert digest.truncated is True
    assert "已截断" in digest.text
    assert digest.omitted_chars > 0


def test_resume_falls_back_with_marker_when_no_structure() -> None:
    digest = build_resume_digest("乙" * 3000)

    assert len(digest.text) <= RESUME_DIGEST_LIMIT
    assert digest.fallback is True
    assert "已截断" in digest.text
    assert digest.omitted_chars > 0


@pytest.mark.parametrize("text", ["", "   \n  ", None])
def test_empty_input_raises(text: object) -> None:
    with pytest.raises(DigestError):
        build_jd_digest(text)
    with pytest.raises(DigestError):
        build_resume_digest(text)


def test_digest_meta_is_body_free() -> None:
    digest = build_jd_digest("负责支付网关" * 300)

    meta = digest_meta(digest, None)

    assert meta["digest_fallback"] is False
    jd_meta = meta["digests"]["jd"]
    assert set(jd_meta) == {
        "kind",
        "limit",
        "original_chars",
        "digest_chars",
        "fallback",
        "truncated",
        "omitted_chars",
    }
    assert "text" not in jd_meta
    assert digest.text not in str(meta)

"""`app/video/article_context.py` 单测：中英关键词字典 + extract_article_context。"""
from __future__ import annotations

import pytest

from app.video.article_context import extract_article_context


class TestExtractArticleContext:
    @pytest.mark.unit
    def test_中文_波兰_华沙_识别为_poland(self) -> None:
        ctx = extract_article_context("难忘的波兰华尔兹", "我们坐火车抵达华沙，举目无亲")
        assert "poland" in ctx["location_tags"]

    @pytest.mark.unit
    def test_英文_Poland_Warsaw_也_命中(self) -> None:
        """援翰写心文章常混排 CJK + 拉丁文，关键词必须双轨。"""
        ctx = extract_article_context(
            "The Polish Waltz", "Bradley met us in Warsaw in 1992."
        )
        assert "poland" in ctx["location_tags"]

    @pytest.mark.unit
    def test_日本_东京_京都_识别为_japan(self) -> None:
        ctx = extract_article_context("京都的雨", "那天从东京出发去京都看樱花")
        assert ctx["location_tags"] == ["japan"]

    @pytest.mark.unit
    def test_中英_混排_也_命中(self) -> None:
        """'Bradley 在 Warsaw 见到了波兰朋友' → poland 命中"""
        ctx = extract_article_context(
            "Some title", "Bradley 在 Warsaw 见到了波兰朋友"
        )
        assert "poland" in ctx["location_tags"]

    @pytest.mark.unit
    def test_无_地域_线索_返回_空(self) -> None:
        ctx = extract_article_context(
            "岁月静好",
            "母亲坐在窗前，手里握着一杯热茶。窗外飘着细雨，像极了那年夏天的蝉鸣。"
        )
        assert ctx["location_tags"] == []

    @pytest.mark.unit
    def test_多_地域_按_命中_次数_降序(self) -> None:
        """'波兰之旅' 标题 → 只返回 ['poland']；正文里偶发的中/俄/美都被屏蔽。"""
        body = (
            "波兰波兰波兰。Bradley 是美国人。我们在华沙见到了波兰朋友。"
            "我们做了一桌中国菜。后来去了莫斯科，又见到了苏联朋友。"
        )
        ctx = extract_article_context("波兰之旅", body)
        # 标题有 poland → 只信标题，正文里的其他地域全屏蔽
        assert ctx["location_tags"] == ["poland"]

    @pytest.mark.unit
    def test_标题_优先_屏蔽_正文_偶发_地域(self) -> None:
        """标题 '难忘的波兰华尔兹' → 即使正文频繁提到中国/苏联/德国/美国，只返回 ['poland']。
        这是 v2 改进的核心：标题 = setting 的强信号，正文里的'中国饭/苏联大使馆'只是借代/食物，
        不应混入 setting。
        """
        body = (
            "一九九二年二月，华沙漫天飞雪。我们做了一桌中国菜，包饺子、烙葱油饼。"
            "柏林的火车。苏联大使馆排了一小时。美国人 Bradley 在波兰工作。"
            "中国饭早把一切都付清了。"
        )
        ctx = extract_article_context("难忘的波兰华尔兹", body)
        assert ctx["location_tags"] == ["poland"]

    @pytest.mark.unit
    def test_正文_兜底_阈值_过滤_偶发(self) -> None:
        """无标题地域 → 用正文 + 阈值过滤。poland 多次提及、china 仅 2 次 → 排除 china。"""
        body = (
            "波兰波兰波兰华沙华沙华沙波兰人波兰人波兰人。"
            "苏联苏联苏联莫斯科。"  # russia = 2 keywords
            "中国饭中国饭。"  # china = 1 keyword（"中国"）
            "德国德国。"  # germany = 1 keyword
        )
        ctx = extract_article_context("一段回忆", body)  # 标题无地域
        assert "poland" in ctx["location_tags"]
        assert "china" not in ctx["location_tags"], "中国 1 次提及应被阈值过滤"
        assert "germany" not in ctx["location_tags"], "德国 1 次提及应被阈值过滤"

    @pytest.mark.unit
    def test_正文_多_地域_都_强_时_都_保留(self) -> None:
        """poland/russia 各 5+ 提及（多 keyword 命中）→ 都保留。"""
        body = (
            "波兰波兰波兰华沙华沙波兰人波兰人波兰语波兰语。"  # poland 5 keywords
            "苏联苏联苏联莫斯科莫斯科苏联人苏联人。"  # russia 3 keywords
        )
        ctx = extract_article_context("一段横跨两国的回忆", body)
        assert "poland" in ctx["location_tags"]
        assert "russia" in ctx["location_tags"]

    @pytest.mark.unit
    def test_前_4k_字_外_的_地域_忽略(self) -> None:
        """body 5000 字后才出现'波兰' → 不命中（避免正文里偶发用词误判）"""
        body = "散文填充。" * 800 + "——但故事发生在波兰。"
        assert len(body) > 4000
        ctx = extract_article_context("通用标题", body)
        assert "poland" not in ctx["location_tags"]

    @pytest.mark.unit
    def test_标题_里_的_地域_也_算(self) -> None:
        """'京都的雨' 即使正文没出现'京都'，标题命中也算"""
        ctx = extract_article_context("京都的雨", "那天下了很大的雨。")
        assert "japan" in ctx["location_tags"]

    @pytest.mark.unit
    def test_返回_结构_是_dict_含_location_tags(self) -> None:
        ctx = extract_article_context("任何标题", "任何正文")
        assert isinstance(ctx, dict)
        assert "location_tags" in ctx
        assert isinstance(ctx["location_tags"], list)
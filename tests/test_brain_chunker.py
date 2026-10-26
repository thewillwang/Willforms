from embody.cloud.brain import SentenceChunker


def feed_all(chunker: SentenceChunker, deltas: list[str]) -> list[str]:
    out: list[str] = []
    for d in deltas:
        out.extend(chunker.feed(d))
    rest = chunker.flush()
    if rest:
        out.append(rest)
    return out


def test_chinese_sentences_split_on_punctuation():
    c = SentenceChunker()
    assert feed_all(c, ["你好呀", "！今天", "天气不错。", "我们出去玩吧？"]) == ["你好呀！", "今天天气不错。", "我们出去玩吧？"]


def test_sentence_released_as_soon_as_next_char_arrives():
    c = SentenceChunker()
    assert c.feed("嘎嘎。") == []          # boundary at end: wait for one more char
    assert c.feed("你") == ["嘎嘎。"]
    assert c.flush() == "你"


def test_english_requires_space_after_period():
    c = SentenceChunker()
    out = c.feed("Pi is 3.14 roughly. Nice")
    assert out == ["Pi is 3.14 roughly."]
    assert c.flush() == "Nice"


def test_english_question_and_exclamation():
    assert feed_all(SentenceChunker(), ["Hi! How", " are you? ", "Good."]) == ["Hi!", "How are you?", "Good."]


def test_punctuation_runs_and_closing_quotes_stay_together():
    c = SentenceChunker()
    assert feed_all(c, ["真的吗？！", "他说“好的。”然后", "走了……", "嗯"]) == ["真的吗？！", "他说“好的。”", "然后走了……", "嗯"]


def test_english_quote_after_period():
    assert feed_all(SentenceChunker(), ['He said "hi." Then left.']) == ['He said "hi."', "Then left."]


def test_ellipsis_ascii():
    assert feed_all(SentenceChunker(), ["Well... maybe."]) == ["Well...", "maybe."]


def test_newline_is_boundary():
    assert feed_all(SentenceChunker(), ["第一行\n第二行"]) == ["第一行", "第二行"]


def test_chinese_semicolon_is_boundary():
    assert feed_all(SentenceChunker(), ["我喜欢水；也喜欢面包"]) == ["我喜欢水；", "也喜欢面包"]


def test_first_sentence_released_early_at_comma():
    c = SentenceChunker(first_soft_limit=20)
    long = "我今天早上起床的时候，发现窗外下着很大很大的雨"  # > 20 chars, no full stop
    out = c.feed(long)
    assert out == ["我今天早上起床的时候，"]
    assert c.pending == "发现窗外下着很大很大的雨"


def test_early_split_only_for_first_sentence():
    c = SentenceChunker(first_soft_limit=10, soft_limit=1000)
    assert c.feed("好的。") == []
    assert c.feed("然") == ["好的。"]
    # second sentence is long with a comma, but no early split any more
    assert c.feed("后我们一起去公园散步，再去河边看鸭子") == []
    assert c.flush() == "然后我们一起去公园散步，再去河边看鸭子"


def test_english_comma_early_split_needs_space():
    c = SentenceChunker(first_soft_limit=30)
    out = c.feed("It costs 1,000 coins, which is a lot for a duck like me")
    assert out == ["It costs 1,000 coins,"]


def test_no_comma_no_early_split():
    c = SentenceChunker(first_soft_limit=5)
    assert c.feed("abcdefghijklmnop") == []
    assert c.flush() == "abcdefghijklmnop"


def test_flush_empty_and_whitespace():
    c = SentenceChunker()
    assert c.flush() == ""
    c.feed("   ")
    assert c.flush() == ""


def test_reset_reenables_first_sentence_rule():
    c = SentenceChunker(first_soft_limit=10)
    c.feed("短句。好")
    c.flush()
    c.reset()
    assert c.emitted == 0
    assert c.feed("一二三四五六，七八九十十一") == ["一二三四五六，"]


def test_char_by_char_streaming_matches_bulk():
    text = "嘎！你回来啦。今天过得怎么样？I missed you. 我一直在等你……"
    bulk = feed_all(SentenceChunker(), [text])
    chars = feed_all(SentenceChunker(), list(text))
    assert bulk == chars == ["嘎！", "你回来啦。", "今天过得怎么样？", "I missed you.", "我一直在等你……"]

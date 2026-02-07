"""Tests for ComicInfo.xml parsing."""

from server.comicinfo import ComicInfoParsed, parse_comicinfo_xml


def test_parse_comicinfo_one_shot():
    """Parse one-shot comic ComicInfo (no Issue, has Title, Summary, etc.)."""
    xml = b"""<?xml version="1.0"?>
<ComicInfo>
  <Title>Family Feud</Title>
  <Series>Carnage</Series>
  <Web>https://www.comixology.com/Carnage/digital-comic/24004</Web>
  <Summary>Collects Carnage #1-5.</Summary>
  <Notes>Scraped metadata from Comixology [CMXDB24004]</Notes>
  <Publisher>Marvel</Publisher>
  <Genre>Superhero</Genre>
  <PageCount>114</PageCount>
  <LanguageISO>en</LanguageISO>
  <Year>2012</Year>
  <Month>4</Month>
  <Writer>Zeb Wells</Writer>
  <Penciller>Clayton Crain</Penciller>
</ComicInfo>"""
    m = parse_comicinfo_xml(xml)
    assert m.title == "Family Feud"
    assert m.writer == "Zeb Wells"
    assert m.penciller == "Clayton Crain"
    assert m.year == 2012
    assert m.month == 4
    assert m.notes == "Scraped metadata from Comixology [CMXDB24004]"
    assert m.summary == "Collects Carnage #1-5."
    assert m.web == "https://www.comixology.com/Carnage/digital-comic/24004"
    assert m.language_iso == "en"
    assert m.genre == "Superhero"
    assert m.publisher == "Marvel"
    # Series is not in ComicInfoParsed (we use folder name when leaf)
    assert "series" not in m.model_dump()


def test_parse_comicinfo_series_issue():
    """Parse series comic with Issue tag (lowercase writer in XML)."""
    xml = b"""<?xml version="1.0"?>
<ComicInfo>
  <Series>Batman </Series>
  <Issue>161</Issue>
  <LanguageISO>en</LanguageISO>
  <PageCount>31</PageCount>
  <Notes>Scraped metadata from Amazon [ASINB0FFY6NJKX]</Notes>
  <writer>Jeph Loeb</writer>
  <Month>7</Month>
  <Year>2025</Year>
</ComicInfo>"""
    m = parse_comicinfo_xml(xml)
    assert m.issue_number == 161
    assert m.writer == "Jeph Loeb"
    assert m.month == 7
    assert m.year == 2025
    assert m.notes == "Scraped metadata from Amazon [ASINB0FFY6NJKX]"
    assert m.language_iso == "en"
    assert "series" not in m.model_dump()


def test_parse_comicinfo_with_namespace():
    """Parse ComicInfo with xmlns attributes (tags may get namespace in some parsers)."""
    xml = b"""<?xml version='1.0' encoding='utf-8'?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <Series>Unbreakable X-Men </Series>
    <Issue>1</Issue>
    <LanguageISO>en</LanguageISO>
    <PageCount>26</PageCount>
    <Notes>Scraped metadata from Amazon [ASINB0FK44W12C]</Notes>
    <writer>Gail Simone</writer>
    <Month>10</Month>
    <Year>2025</Year>
</ComicInfo>"""
    m = parse_comicinfo_xml(xml)
    assert m.issue_number == 1
    assert m.writer == "Gail Simone"
    assert m.month == 10
    assert m.year == 2025
    assert m.notes == "Scraped metadata from Amazon [ASINB0FK44W12C]"
    assert m.language_iso == "en"
    assert "series" not in m.model_dump()


def test_parse_comicinfo_empty_invalid():
    """Empty or invalid XML returns ComicInfoParsed with no fields set."""
    for xml in (b"", b"<root></root>", b"not xml at all"):
        m = parse_comicinfo_xml(xml)
        assert m.model_dump(exclude_none=True) == {}

from taskarena.channel_format import build_channel_xml


def test_basic_content():
    xml = build_channel_xml("hello")
    assert xml == "<channel>hello</channel>"


def test_attrs_included():
    xml = build_channel_xml("msg", source="taskarena", type="health")
    assert 'source="taskarena"' in xml
    assert 'type="health"' in xml
    assert ">msg</channel>" in xml


def test_none_attrs_excluded():
    xml = build_channel_xml("msg", source="taskarena", task_id=None)
    assert "task_id" not in xml
    assert 'source="taskarena"' in xml


def test_escapes_content():
    xml = build_channel_xml("<b>bold</b> & more")
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; more" in xml


def test_escapes_attr_value():
    xml = build_channel_xml("msg", user='O"Brien')
    assert '&quot;' in xml


def test_scheduled_format():
    xml = build_channel_xml("Daily digest", source="taskarena", type="scheduled", schedule="daily")
    assert 'type="scheduled"' in xml
    assert 'schedule="daily"' in xml
    assert "Daily digest" in xml

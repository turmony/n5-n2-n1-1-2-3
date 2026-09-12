import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urljoin, urlsplit

from jlpt_notes.reader.builder import build_site

CONFIG = Path(__file__).resolve().parents[2] / 'reader/mkdocs.yml'


def test_document_links_resolve_without_changing_code_or_external_links(caplog):
    with TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / 'notes'
        draft = root / 'drafts/draft.md'
        card = root / 'grammar/n3/N3-G-0031.md'
        draft.parent.mkdir(parents=True)
        card.parent.mkdir(parents=True)
        card.write_text('# Grammar\n\n## Detail\n', encoding='utf-8')
        (root / 'events.jsonl').write_text('{}\n', encoding='utf-8')
        draft.write_text(
            '# Draft\n\n[formal](../grammar/n3/N3-G-0031.md?view=1#detail)\n\n'
            '[reference][card]\n\n[card]: ../grammar/n3/N3-G-0031.md\n\n'
            '[events](../events.jsonl)\n\n'
            '[external](https://example.com/card.md)\n\n'
            '`[code](../grammar/n3/N3-G-0031.md)`\n', encoding='utf-8'
        )
        before = draft.read_bytes()
        site = base / 'site'
        result = build_site(root, CONFIG, site)
        assert result.success, result.error
        assert 'not found among documentation files' not in caplog.text
        page = site / 'library/drafts/draft.md.__reader_markdown__/index.html'
        html = page.read_text(encoding='utf-8')
        for label in ('formal', 'reference', 'events'):
            href = re.search(r'<a href="([^"]+)">' + label + '</a>', html)[1]
            url = urlsplit(urljoin('/' + page.relative_to(site).as_posix(), href))
            assert (site / unquote(url.path).lstrip('/') / 'index.html').is_file()
            if label == 'formal':
                assert url.query == 'view=1'
                assert url.fragment == 'detail'
        assert 'href="https://example.com/card.md"' in html
        assert '<code>[code](../grammar/n3/N3-G-0031.md)</code>' in html
        assert draft.read_bytes() == before

import base64
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urljoin, urlsplit

from jlpt_notes.reader.builder import build_site
from jlpt_notes.reader.plugin import _sanitize_html
from jlpt_notes.reader.sources import load_source_pages
from jlpt_notes.reader.watcher import snapshot_sources

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
CONFIG = Path(__file__).resolve().parents[2] / 'reader/mkdocs.yml'


def test_images_publish_at_resolved_markdown_urls_and_refresh_without_source_writes(caplog):
    with TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / 'notes'
        card = root / 'grammar/n3/N3-G-0052.md'
        image = root / 'assets/grammar/n3/board.png'
        card.parent.mkdir(parents=True)
        image.parent.mkdir(parents=True)
        card.write_text('# Card\n\n![board](../../assets/grammar/n3/board.png)\n\n[open](../../assets/grammar/n3/board.png)\n', encoding='utf-8')
        image.write_bytes(PNG)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (card, image)}
        site = base / 'site'
        first = build_site(root, CONFIG, site)
        assert first.success, first.error
        assert 'not found among documentation files' not in caplog.text
        page = site / 'library/grammar/n3/N3-G-0052.md.__reader_markdown__/index.html'
        html = page.read_text(encoding='utf-8')
        src = re.search(r'<img[^>]+src="([^"]+)"', html)
        assert src, 'board image was removed from article'
        target = site / urljoin('/' + page.relative_to(site).as_posix(), src[1]).lstrip('/')
        assert target.read_bytes() == PNG
        assert 'library/assets/grammar/n3/board.png' == target.relative_to(site).as_posix()
        assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
        stamps = snapshot_sources(root)
        image.write_bytes(PNG + b'changed')
        assert snapshot_sources(root) != stamps
        second_site = base / 'site2'
        second = build_site(root, CONFIG, second_site, previous_site=site)
        assert second.success, second.error
        assert second.version != first.version
        assert (second_site / target.relative_to(site)).read_bytes() == PNG + b'changed'
        image.unlink()
        third_site = base / 'site3'
        third = build_site(root, CONFIG, third_site, previous_site=second_site)
        assert third.success, third.error
        assert not (third_site / target.relative_to(site)).exists()


def test_images_are_watched_but_not_catalogued_and_private_files_stay_excluded():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'card.md').write_text('# Card', encoding='utf-8')
        (root / 'board.PNG').write_bytes(PNG)
        (root / '.private.png').write_bytes(PNG)
        (root / 'secret.txt').write_text('private', encoding='utf-8')
        assert [p.relative_path.name for p in load_source_pages(root)] == ['card.md']
        assert {p.path for p in snapshot_sources(root)} == {'card.md', 'board.PNG'}


def test_image_sanitizer_preserves_image_but_rejects_active_attributes():
    html = _sanitize_html('<img src="../board.png" alt="board" onerror="alert(1)"><img src="javascript:alert(1)">')
    assert 'src="../board.png"' in html
    assert 'alt="board"' in html
    assert 'onerror' not in html
    assert 'javascript:' not in html


def test_image_added_after_page_is_discovered_and_resolves_on_incremental_build(caplog):
    with TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / 'notes'
        root.mkdir()
        (root / 'card.md').write_text('# Card\n\n![new](assets/new/board.png)\n', encoding='utf-8')
        site = base / 'site'
        first = build_site(root, CONFIG, site)
        assert first.success
        before = snapshot_sources(root)
        image = root / 'assets/new/board.png'
        image.parent.mkdir(parents=True)
        image.write_bytes(PNG)
        assert snapshot_sources(root) != before
        caplog.clear()
        next_site = base / 'site2'
        second = build_site(root, CONFIG, next_site, previous_site=site)
        assert second.success, second.error
        assert second.version != first.version
        assert 'not found among documentation files' not in caplog.text
        assert (next_site / 'library/assets/new/board.png').read_bytes() == PNG
        html = (next_site / 'library/card.md.__reader_markdown__/index.html').read_text(encoding='utf-8')
        assert 'src="../assets/new/board.png"' in html


def test_missing_image_reports_source_and_placeholder_then_clears_on_repair(tmp_path):
    root = tmp_path / 'notes'
    root.mkdir()
    card = root / 'card.md'
    card.write_text('![板书][board]\n\n[board]: assets/board.png\n', encoding='utf-8')
    before = card.read_bytes(), card.stat().st_mtime_ns
    site = tmp_path / 'site'
    first = build_site(root, CONFIG, site)
    assert first.success
    assert len(first.warnings) == 1
    assert 'card.md' in first.warnings[0] and 'assets/board.png' in first.warnings[0]
    assert first.log_path.is_file()
    html = (site / 'library/card.md.__reader_markdown__/index.html').read_text(encoding='utf-8')
    assert '图片暂不可用' in html
    assert '<img' not in html.split('<article', 1)[1].split('</article>', 1)[0]
    image = root / 'assets/board.png'
    image.parent.mkdir()
    image.write_bytes(PNG)
    second = build_site(root, CONFIG, tmp_path / 'site2', previous_site=site)
    assert second.success and not second.warnings
    html = (tmp_path / 'site2/library/card.md.__reader_markdown__/index.html').read_text(encoding='utf-8')
    assert '图片暂不可用' not in html
    assert 'src="../assets/board.png"' in html
    assert (card.read_bytes(), card.stat().st_mtime_ns) == before


def test_missing_raw_html_image_gets_same_placeholder(tmp_path):
    root = tmp_path / 'notes'
    root.mkdir()
    (root / 'card.md').write_text('<img src="assets/missing.png" alt="原图"> 后文', encoding='utf-8')
    site = tmp_path / 'site'
    result = build_site(root, CONFIG, site)
    assert result.success and result.warnings
    html = (site / 'library/card.md.__reader_markdown__/index.html').read_text(encoding='utf-8')
    assert '图片暂不可用：原图' in html and '后文' in html
    assert 'src="assets/missing.png"' not in html


def test_promoted_markdown_and_raw_html_images_resolve_to_published_bytes(tmp_path):
    from jlpt_notes.asset_links import rebase_assets

    root = tmp_path / 'notes'
    image = root / 'assets/板书 (1).png'
    image.parent.mkdir(parents=True)
    image.write_bytes(PNG)
    body = ('![图](<../assets/板书 (1).png>)\n\n'
            '<img src="../assets/板书%20%281%29.png?x=1&amp;y=2#图" alt="原图">\n')
    card = root / 'grammar/n3/card.md'
    card.parent.mkdir(parents=True)
    card.write_text(rebase_assets(root, Path('drafts/card.md'), Path('grammar/n3/card.md'), body), encoding='utf-8')
    site = tmp_path / 'site'
    result = build_site(root, CONFIG, site)
    assert result.success and not result.warnings
    page = site / 'library/grammar/n3/card.md.__reader_markdown__/index.html'
    html = page.read_text(encoding='utf-8')
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)
    assert len(sources) == 2
    for source in sources:
        target = unquote(urlsplit(urljoin('/' + page.relative_to(site).as_posix(), source)).path).lstrip('/')
        assert target == 'library/assets/板书 (1).png'
        assert (site / target).read_bytes() == PNG

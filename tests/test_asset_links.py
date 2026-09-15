import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from test_repository import sample_card

from jlpt_notes.repository import Repository


def test_promotion_rebases_images_references_and_links_without_touching_examples(tmp_path):
    repo = Repository(tmp_path / 'notes')
    image = repo.root / 'assets/板书 (1).png'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'image')
    body = ('![图](<../assets/板书 (1).png> "标题")\n'
            '[打开](../assets/板书%20%281%29.png?q=1#part)\n'
            '![引用][board]\n\n[board]: ../assets/板书%20%281%29.png "标题"\n\n'
            '`![例](../assets/missing.png)`\n\n'
            '```md\n![例](../assets/missing.png)\n```\n\n'
            '    ![例](../assets/missing.png)\n\n'
            '![外链](https://example.org/a.png)\n')
    draft = repo.create_draft('学习者原话', replace(sample_card(), body=body))
    before = draft.read_text(encoding='utf-8').split('\n---\n\n', 1)[1]
    card = repo.confirm_draft(draft.stem, date(2026, 9, 15))
    assert card.body == body.replace('../assets/板书', '../../assets/板书')
    assert draft.read_text(encoding='utf-8').split('\n---\n\n', 1)[1] == before
    assert card.next_review == date(2026, 9, 22)


@pytest.mark.parametrize('link', ['../assets/missing.png', '../../outside.png', '../.private/a.png'])
def test_invalid_image_blocks_confirmation_without_any_writes(tmp_path, link):
    repo = Repository(tmp_path / 'notes')
    draft = repo.create_draft('原话', replace(sample_card(), body=f'![图]({link})'))
    before = {p: p.read_bytes() for p in repo.root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='图片|资源|链接'):
        repo.confirm_draft(draft.stem, date(2026, 9, 15))
    assert {p: p.read_bytes() for p in repo.root.rglob('*') if p.is_file()} == before
    assert not json.loads(draft.read_text(encoding='utf-8').split('---')[1])['confirmed']


def test_repository_images_are_publishable():
    from jlpt_notes.asset_links import audit_assets
    root = Path(__file__).resolve().parents[1] / 'jlpt-notes'
    assert audit_assets(root) == ()


def test_link_check_cli_is_read_only_and_returns_failure(tmp_path, monkeypatch, capsys):
    import sys

    from jlpt_notes.cli import main

    card = tmp_path / 'card.md'
    card.write_text('![图](assets/missing.png)', encoding='utf-8')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(sys, 'argv', ['jlpt-notes', 'validate-links', '--root', str(tmp_path)])
    assert main() == 1
    assert 'card.md' in capsys.readouterr().err
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()} == before
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/missing.png').write_bytes(b'image')
    assert main() == 0


@pytest.mark.parametrize('link', [
    '../../../outside.png', '%2e%2e/%2e%2e/%2e%2e/outside.png',
    '../../.private/a.png', '../../assets/a.svg', 'file:///C:/private.png',
    '../../assets/alias.png', '../../assets/linked/a.png',
])
def test_audit_rejects_unpublishable_targets_even_if_files_exist(tmp_path, link):
    from jlpt_notes.asset_links import AssetIndex

    root = tmp_path / 'notes'
    (root / 'assets').mkdir(parents=True)
    (root / '.private').mkdir()
    (root / '.private/a.png').write_bytes(b'image')
    (root / 'assets/a.svg').write_text('<svg/>')
    (tmp_path / 'outside.png').write_bytes(b'image')
    real = root / 'assets/a.png'
    real.write_bytes(b'image')
    try:
        (root / 'assets/alias.png').symlink_to(real)
        (root / 'assets/linked').symlink_to(root / '.private', target_is_directory=True)
    except OSError:
        if 'alias' in link or 'linked' in link:
            pytest.skip('symlink privileges unavailable')
    assert AssetIndex(root).issue(Path('grammar/n3/card.md'), link) is not None


def test_rebase_at_arbitrary_depth_preserves_entities_and_literal_same_url(tmp_path):
    from jlpt_notes.asset_links import rebase_assets

    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/a.png').write_bytes(b'image')
    body = ('<img src="../../assets/a.png?x=1&amp;y=2#图" alt="图">\n\n'
            '![图](../../assets/a.png) 文字\n\n'
            '`![例](../../assets/a.png)`\n\n'
            '~~~markdown\n![例](../../assets/a.png)\n~~~\n')
    result = rebase_assets(tmp_path, Path('drafts/batch/card.md'), Path('grammar/n3/nested/card.md'), body)
    assert result == body.replace('../../assets/a.png', '../../../assets/a.png', 2)


def test_rebase_does_not_edit_markdown_examples_inside_html_attributes(tmp_path):
    from jlpt_notes.asset_links import rebase_assets

    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/a.png').write_bytes(b'image')
    body = ('![图](../assets/a.png)\n\n'
            '<span title="![例](../assets/a.png)">原文</span>\n'
            '<img src="../assets/a.png" data-src="../assets/a.png" alt="图">')
    result = rebase_assets(tmp_path, Path('drafts/card.md'), Path('grammar/n3/card.md'), body)
    expected = body.replace('![图](../assets/', '![图](../../assets/').replace('<img src="../assets/', '<img src="../../assets/')
    assert result == expected

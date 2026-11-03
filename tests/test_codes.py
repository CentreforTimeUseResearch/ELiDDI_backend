import pytest

from app import codes


def test_generated_code_has_the_default_length_and_alphabet():
    code = codes.generate_code()

    assert len(code) == 8
    assert set(code) <= set(codes.DEFAULT_ALPHABET)


def test_alphabet_has_no_look_alike_characters():
    assert len(codes.DEFAULT_ALPHABET) == 31
    assert not set('01OIL') & set(codes.DEFAULT_ALPHABET)


def test_length_and_alphabet_can_be_changed():
    code = codes.generate_code(length=12, alphabet='AB')

    assert len(code) == 12
    assert set(code) <= {'A', 'B'}


def test_generated_codes_differ():
    assert len({codes.generate_code() for _ in range(50)}) == 50


@pytest.mark.parametrize('typed', ['abcd-efgh', 'ABCDEFGH', ' abcd efgh ', 'AbCd-EfGh', 'ABCD - EFGH'])
def test_normalize_ignores_case_spaces_and_hyphens(typed):
    assert codes.normalize_code(typed) == 'ABCDEFGH'


def test_format_groups_in_fours():
    assert codes.format_code('ABCDEFGH') == 'ABCD-EFGH'
    assert codes.format_code('ABCDEFGHJK') == 'ABCD-EFGH-JK'


def test_the_same_code_typed_differently_has_the_same_hash():
    assert codes.hash_code('abcd-efgh', 'k') == codes.hash_code('ABCDEFGH', 'k')


def test_hash_depends_on_the_code_and_the_key():
    assert codes.hash_code('ABCDEFGH', 'k') != codes.hash_code('ABCDEFGJ', 'k')
    assert codes.hash_code('ABCDEFGH', 'k') != codes.hash_code('ABCDEFGH', 'other')


def test_hash_does_not_contain_the_code():
    assert 'ABCDEFGH' not in codes.hash_code('ABCDEFGH', 'k')


def test_hash_key_comes_from_the_environment_when_set(tmp_path):
    assert codes.load_hash_key(tmp_path, {'ELIDDI_CODE_HASH_KEY': 'from-env'}) == 'from-env'
    assert not (tmp_path / 'code_hash_key').exists()


def test_hash_key_is_created_once_and_then_reused(tmp_path):
    first = codes.load_hash_key(tmp_path / 'state', {})
    second = codes.load_hash_key(tmp_path / 'state', {})

    assert first == second
    assert len(first) == 64

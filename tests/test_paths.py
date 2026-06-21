from groupthink.web.app import _clean_folder_path


def test_strips_double_quotes():
    assert _clean_folder_path('"/Users/me/My Drive/Sessions"') == "/Users/me/My Drive/Sessions"


def test_strips_single_quotes():
    assert _clean_folder_path("'/Users/me/Sessions'") == "/Users/me/Sessions"


def test_unescapes_shell_spaces():
    assert _clean_folder_path("/Users/me/My\\ Drive/Sessions") == "/Users/me/My Drive/Sessions"


def test_plain_path_unchanged():
    assert _clean_folder_path("  /Users/me/Sessions  ") == "/Users/me/Sessions"

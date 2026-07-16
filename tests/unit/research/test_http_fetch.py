"""Unit tests for the httpx-SSR routing helpers (pure, no network)."""

from src.actions.research.http_fetch import (
    host_in_allowlist,
    instagram_handle,
    is_instagram,
    rewrite_url,
)


class TestAllowlist:
    def test_exact_host_matches(self):
        assert host_in_allowlist("https://zoon.ru/spb/x/")
        assert host_in_allowlist("https://prodoctorov.ru/spb/lpu/1/")

    def test_subdomain_matches_parent_entry(self):
        # spb.hh.ru should match the allowlist entry "hh.ru"
        assert host_in_allowlist("https://spb.hh.ru/employer/1")
        assert host_in_allowlist("https://spb.spravker.ru/x/y.htm")

    def test_www_is_normalised(self):
        assert host_in_allowlist("https://www.rusprofile.ru/id/1")

    def test_social_and_spa_excluded(self):
        # VK and 2gis return stubs/interstitials — must stay on the browser path.
        assert not host_in_allowlist("https://vk.com/club1")
        assert not host_in_allowlist("https://2gis.ru/spb/firm/1")
        assert not host_in_allowlist("https://example.com/")


class TestInstagram:
    def test_is_instagram(self):
        assert is_instagram("https://www.instagram.com/foo/")
        assert is_instagram("https://instagram.com/foo")
        assert not is_instagram("https://vk.com/foo")

    def test_handle_from_profile(self):
        assert instagram_handle("https://www.instagram.com/pobokalam.spb/") == "pobokalam.spb"

    def test_post_and_reel_have_no_handle(self):
        assert instagram_handle("https://www.instagram.com/p/C38Pg9rtnap/") == ""
        assert instagram_handle("https://www.instagram.com/reel/ABC/") == ""


class TestRewrite:
    def test_tme_to_s_preview(self):
        assert rewrite_url("https://t.me/maximumauto") == "https://t.me/s/maximumauto"

    def test_tme_already_preview_unchanged(self):
        assert rewrite_url("https://t.me/s/maximumauto") == "https://t.me/s/maximumauto"

    def test_non_tme_unchanged(self):
        assert rewrite_url("https://zoon.ru/spb/x/") == "https://zoon.ru/spb/x/"

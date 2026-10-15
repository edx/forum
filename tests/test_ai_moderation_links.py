"""Tests for removing trusted links from content before it is classified."""

import pytest

from forum.ai_moderation.links import is_blank, strip_trusted_links

TRUSTED = ("codepen.io", "github.com", "developer.mozilla.org")


class TestStripTrustedLinks:
    """Tests for strip_trusted_links."""

    @pytest.mark.parametrize(
        "content, expected",
        [
            (
                "My pen: https://codepen.io/learner/pen/abcXYZ can you help?",
                "My pen:  can you help?",
            ),
            ("http://codepen.io/learner/pen/abcXYZ", ""),
            ("See codepen.io/learner/pen/abcXYZ please", "See  please"),
            ("Try https://www.codepen.io/pen/1.", "Try "),
            ("Docs: https://developer.mozilla.org/en-US/docs/Web/CSS/flex", "Docs: "),
            ("Fork https://gist.github.com/someone/123", "Fork "),
            ("HTTPS://CODEPEN.IO/LEARNER/PEN/1 thanks", " thanks"),
            ("https://codepen.io:443/pen/1?editors=1100#top done", " done"),
            ("I love codepen.io.", "I love ."),
        ],
    )
    def test_trusted_urls_are_removed(self, content: str, expected: str) -> None:
        """A trusted URL is removed whatever its scheme, case, subdomain or path."""
        assert strip_trusted_links(content, TRUSTED) == expected

    @pytest.mark.parametrize(
        "content",
        [
            "Visit https://top-grade-helpers.example/order now",
            "https://codepen.io.evil.example/pen/1",
            "https://notcodepen.io/pen/1",
            "https://codepen-io.example/pen/1",
            "mail me at someone@codepen.io",
            "www.example.com and https://example.org/codepen",
        ],
    )
    def test_other_urls_are_left_alone(self, content: str) -> None:
        """Lookalike and untrusted hosts are left for the classifier to judge."""
        assert strip_trusted_links(content, TRUSTED) == content

    def test_untrusted_host_stays_visible_when_a_trusted_url_is_embedded(
        self,
    ) -> None:
        """
        Removing a trusted URL that sits inside another URL never hides the
        untrusted host around it.
        """
        content = "Go to https://evil.example/?next=https://codepen.io/pen/1"

        assert "https://evil.example/" in strip_trusted_links(content, TRUSTED)

    def test_trusted_anchor_is_replaced_by_its_text(self) -> None:
        """The editor writes links as anchors; a trusted one becomes plain text."""
        content = (
            '<p>Here is <a href="https://codepen.io/learner/pen/abc" '
            'target="_blank" rel="noopener">my pen</a>, what is wrong?</p>'
        )

        assert strip_trusted_links(content, TRUSTED) == (
            "<p>Here is my pen, what is wrong?</p>"
        )

    def test_autolinked_trusted_url_is_removed_entirely(self) -> None:
        """An autolinked URL is both the href and the text; neither is left."""
        content = (
            '<p><a href="https://codepen.io/learner/pen/abc">'
            "https://codepen.io/learner/pen/abc</a></p>"
        )

        assert strip_trusted_links(content, TRUSTED) == "<p></p>"

    def test_untrusted_anchor_is_kept(self) -> None:
        """
        An anchor to an untrusted host is kept, even when its text is a trusted
        URL: the href is what a reader would actually follow.
        """
        content = (
            '<p><a href="https://evil.example/landing">'
            "https://codepen.io/learner/pen/abc</a></p>"
        )

        assert strip_trusted_links(content, TRUSTED) == (
            '<p><a href="https://evil.example/landing"></a></p>'
        )

    def test_rest_of_a_spam_post_is_kept(self) -> None:
        """A trusted link does not take the spam around it out of the post."""
        content = "Guaranteed A grades! WhatsApp +1-555-0199 https://codepen.io/pen/1"

        assert strip_trusted_links(content, TRUSTED) == (
            "Guaranteed A grades! WhatsApp +1-555-0199 "
        )

    @pytest.mark.parametrize("domains", [(), [], None, ("", "  ")])
    def test_no_trusted_domains_leaves_content_unchanged(self, domains: object) -> None:
        """With nothing trusted, every link is classified like any other text."""
        content = "My pen: https://codepen.io/learner/pen/abc"

        assert strip_trusted_links(content, domains) == content  # type: ignore[arg-type]

    def test_domains_are_normalized(self) -> None:
        """Domains configured with odd case, padding or dots still match."""
        content = "My pen: https://codepen.io/learner/pen/abc"

        assert strip_trusted_links(content, [" .CodePen.IO. "]) == "My pen: "

    def test_reported_case(self) -> None:
        """LP-1310: CodePen links in a W3C CSS course were deleted as spam."""
        content = "<p>My solution: https://codepen.io/w3cx/pen/abc</p>"

        assert strip_trusted_links(content, TRUSTED) == "<p>My solution: </p>"


class TestIsBlank:
    """Tests for is_blank."""

    @pytest.mark.parametrize(
        "content", ["", "   ", "<p></p>", "<p> </p>\n<p>&nbsp;</p>", "<br/><br />"]
    )
    def test_blank_content(self, content: str) -> None:
        """Whitespace and bare wrapping tags leave nothing to classify."""
        assert is_blank(content) is True

    @pytest.mark.parametrize(
        "content",
        [
            "hi",
            "<p>hi</p>",
            '<p><img src="https://spam.example/ad.png"></p>',
            '<p><a href="https://evil.example"></a></p>',
        ],
    )
    def test_content_to_classify(self, content: str) -> None:
        """Text, or any tag carrying attributes, is still worth classifying."""
        assert is_blank(content) is False

"""Unit tests for the `invoicer help` command.

Verifies every declared topic has a corresponding markdown file that
actually ships with the package and can be loaded via importlib.resources.
"""

import pytest

from invoicer.help_cmd import TOPICS, _load_topic, list_topics, show_topic


class TestTopicManifest:
    def test_topics_not_empty(self):
        assert len(TOPICS) >= 5

    def test_every_topic_has_loadable_content(self):
        for name in TOPICS:
            content = _load_topic(name)
            assert content, f"Topic {name!r} has empty content"
            assert len(content) > 200, (
                f"Topic {name!r} is suspiciously short ({len(content)} chars)"
            )

    def test_every_topic_starts_with_a_heading(self):
        for name in TOPICS:
            content = _load_topic(name)
            first_line = content.strip().split("\n", 1)[0]
            assert first_line.startswith("#"), (
                f"Topic {name!r} must start with a markdown heading, got {first_line!r}"
            )


class TestListTopics:
    def test_list_topics_runs_without_error(self, capsys):
        list_topics()
        captured = capsys.readouterr()
        # Every topic name should appear in the output
        for name in TOPICS:
            assert name in captured.out, (
                f"Topic {name!r} missing from list_topics output"
            )

    def test_list_topics_includes_commands(self, capsys):
        """Regression: `invoicer help` must show the command list, not just topics."""
        list_topics()
        captured = capsys.readouterr()
        # Top-level commands that should always be present
        for cmd in ["init", "discover", "draft", "finalize", "mail-draft", "help"]:
            assert cmd in captured.out, (
                f"Command {cmd!r} missing from `invoicer help` output"
            )
        # Sub-commands from the `client` group
        for sub in ["client add"]:
            assert sub in captured.out, (
                f"Subcommand {sub!r} missing from `invoicer help` output"
            )


class TestShowTopic:
    @pytest.mark.parametrize("topic", list(TOPICS.keys()))
    def test_show_valid_topic(self, topic, capsys):
        show_topic(topic)
        captured = capsys.readouterr()
        assert captured.out, f"show_topic({topic!r}) produced no output"

    def test_unknown_topic_exits(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            show_topic("no-such-topic")
        assert exc_info.value.code == 1


class TestGmailModuleSafety:
    """Regression: gmail.py must not import smtplib or call any `.send()` method.

    The safety property of the tool is enforced at the code level (not at the
    OAuth scope level — `gmail.modify` technically permits sending). These
    tests fail if any future contributor introduces a send-adjacent call.
    """

    def _parse_gmail_module(self):
        import ast
        from pathlib import Path

        import invoicer.gmail as gmail_module

        source = Path(gmail_module.__file__).read_text()
        return ast.parse(source), source

    def test_gmail_module_does_not_import_smtplib(self):
        tree, _ = self._parse_gmail_module()
        import ast

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "smtplib", (
                        "gmail.py must not import smtplib"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "smtplib", (
                    "gmail.py must not import from smtplib"
                )

    def test_gmail_module_has_no_send_calls(self):
        """Walk the AST and reject any Call whose callable is an Attribute named 'send'.

        This catches `foo.send()`, `drafts().send()`, `messages().send()`,
        `service.users().messages().send()`, etc. AST-based so docstrings
        and comments that mention `.send` as prose don't trip it.
        """
        tree, _ = self._parse_gmail_module()
        import ast

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "send", (
                    f"gmail.py must never call .send() — found at line {node.lineno}"
                )

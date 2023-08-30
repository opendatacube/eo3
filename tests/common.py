import operator
from typing import Dict, Iterable, Mapping, Sequence

import rapidjson
from click.testing import CliRunner, Result
from deepdiff import DeepDiff
from deepdiff.model import DiffLevel

from eo3.validation_msg import Level, ValidationMessage, ValidationMessages


def assert_same(expected_doc: Dict, generated_doc: Dict):
    """
    Assert two documents are the same, ignoring trivial float differences
    """
    __tracebackhide__ = operator.methodcaller("errisinstance", AssertionError)
    doc_diffs = DeepDiff(expected_doc, generated_doc, significant_digits=6)
    assert doc_diffs == {}, "\n".join(format_doc_diffs(expected_doc, generated_doc))


def run_prepare_cli(invoke_script, *args, expect_success=True) -> Result:
    """Run the prepare script as a command-line command"""
    __tracebackhide__ = True

    res: Result = CliRunner().invoke(
        invoke_script, [str(a) for a in args], catch_exceptions=False
    )

    if expect_success:
        assert res.exit_code == 0, f"Failed with output: {res.output}"

    return res


def format_doc_diffs(left: Dict, right: Dict) -> Iterable[str]:
    """
    Get a human-readable list of differences in the given documents.

    Returns a list of lines to print.
    """
    doc_diffs = DeepDiff(left, right, significant_digits=6)
    out = []
    if doc_diffs:
        out.append("Documents differ:")
    else:
        out.append("Doc differs in minor float precision:")
        doc_diffs = DeepDiff(left, right)

    def clean_offset(offset: str):
        if offset.startswith("root"):
            return offset[len("root") :]
        return offset

    if "values_changed" in doc_diffs:
        for offset, change in doc_diffs["values_changed"].items():
            out.extend(
                (
                    f"   {clean_offset(offset)}: ",
                    f'          {change["old_value"]!r}',
                    f'       != {change["new_value"]!r}',
                )
            )
    if "dictionary_item_added" in doc_diffs:
        out.append("Added fields:")
        for offset in doc_diffs.tree["dictionary_item_added"].items:
            offset: DiffLevel
            out.append(f"    {clean_offset(offset.path())} = {repr(offset.t2)}")
    if "dictionary_item_removed" in doc_diffs:
        out.append("Removed fields:")
        for offset in doc_diffs.tree["dictionary_item_removed"].items:
            offset: DiffLevel
            out.append(f"    {clean_offset(offset.path())} = {repr(offset.t1)}")
    # Anything we missed from the (sometimes changing) diff api?
    if len(out) == 1:
        out.append(repr(doc_diffs))

    # If pytest verbose:
    out.extend(("Full output document: ", repr(left)))
    return out


def dump_roundtrip(generated_doc):
    """Do a dump/load to normalise all doc-neutral dict/date/tuple/list types.

    The in-memory choice of dict/etc subclasses shouldn't matter, as long as the doc
    is identical once produced.
    """
    return rapidjson.loads(
        rapidjson.dumps(generated_doc, datetime_mode=True, uuid_mode=True)
    )


class MessageCatcher:
    def __init__(self, msgs: ValidationMessages):
        self._msgs: Mapping[Level, Sequence[ValidationMessage]] = {
            Level.info: [],
            Level.warning: [],
            Level.error: [],
        }
        for msg in msgs:
            self._msgs[msg.level].append(msg)

    def errors(self):
        return self._msgs[Level.error]

    def warnings(self):
        return self._msgs[Level.warning]

    def infos(self):
        return self._msgs[Level.info]

    def all_text(self):
        return self.error_text() + self.warning_text() + self.info_text()

    def error_text(self):
        return self.text_for_level(Level.error)

    def warning_text(self):
        return self.text_for_level(Level.warning)

    def info_text(self):
        return self.text_for_level(Level.info)

    def text_for_level(self, lvl: Level):
        txt = ""
        for msg in self._msgs[lvl]:
            txt += str(msg)
        return txt

"""人工校订（revise）测试。"""

import pytest

from app import reviser
from app.assembler import AssemblyError, assemble
from app.reviser import RevisionConflictError, RevisionError, revise

SEGMENTS = ["学而?习之", "时习之不", "之不亦乐乎"]
# 拼接结果 text = "学而时习之不亦乐乎"
# 输出位置 2（时）来源：段0 下标2（?）、段1 下标0（时）
# 输出位置 5（不）来源：段1 下标3、段2 下标1


def test_single_edit_rewrites_one_position():
    r = revise(SEGMENTS, [{"segment": 2, "pos": 2, "char": "而"}])
    assert r["text"] == "学而时习之不而乐乎"      # 仅位置 6（亦）被改写
    assert r["sources"] == assemble(SEGMENTS)["sources"]  # 沿用拼接来源
    assert r["changes"] == [
        {
            "pos": 6,
            "from": "亦",
            "to": "而",
            "edits": [{"segment": 2, "pos": 2, "char": "而"}],
        }
    ]


def test_overlapping_edits_same_char_merged():
    # 段0 下标2 与 段1 下标0 指向同一输出位置 2，改字相同 -> 合并为一处修改
    edits = [
        {"segment": 0, "pos": 2, "char": "時"},
        {"segment": 1, "pos": 0, "char": "時"},
    ]
    r = revise(SEGMENTS, edits)
    assert r["text"] == "学而時习之不亦乐乎"
    assert r["changes"] == [
        {"pos": 2, "from": "时", "to": "時", "edits": edits}
    ]


def test_overlapping_edits_different_chars_conflict():
    edits = [
        {"segment": 0, "pos": 2, "char": "時"},
        {"segment": 1, "pos": 0, "char": "明"},
    ]
    with pytest.raises(RevisionConflictError) as exc:
        revise(SEGMENTS, edits)
    assert exc.value.conflicts == [{"pos": 2, "edits": edits}]


def test_multiple_positions_conflict_all_listed():
    edits = [
        {"segment": 0, "pos": 2, "char": "時"},   # 位置 2：冲突
        {"segment": 1, "pos": 0, "char": "明"},
        {"segment": 1, "pos": 3, "char": "弗"},   # 位置 5：冲突
        {"segment": 2, "pos": 1, "char": "否"},
    ]
    with pytest.raises(RevisionConflictError) as exc:
        revise(SEGMENTS, edits)
    assert [c["pos"] for c in exc.value.conflicts] == [2, 5]
    assert exc.value.conflicts[0]["edits"] == edits[:2]
    assert exc.value.conflicts[1]["edits"] == edits[2:]


def test_segment_index_out_of_range():
    with pytest.raises(RevisionError):
        revise(SEGMENTS, [{"segment": 3, "pos": 0, "char": "甲"}])
    with pytest.raises(RevisionError):
        revise(SEGMENTS, [{"segment": -1, "pos": 0, "char": "甲"}])


def test_pos_out_of_range():
    # 段0 "学而?习之" 共 5 字，合法下标 0～4
    with pytest.raises(RevisionError):
        revise(SEGMENTS, [{"segment": 0, "pos": 5, "char": "甲"}])
    with pytest.raises(RevisionError):
        revise(SEGMENTS, [{"segment": 0, "pos": -1, "char": "甲"}])


def test_unmapped_coordinate_rejected(monkeypatch):
    # 防御性：来源中不存在该坐标（正常拼接不会发生）
    monkeypatch.setattr(
        reviser,
        "assemble",
        lambda segs: {
            "text": "甲乙",
            "sources": [[{"segment": 0, "pos": 0}], [{"segment": 0, "pos": 1}]],
        },
    )
    with pytest.raises(RevisionError, match="未映射"):
        reviser.revise(["甲乙", "丙丁"], [{"segment": 1, "pos": 0, "char": "甲"}])


def test_multi_mapped_coordinate_rejected(monkeypatch):
    # 防御性：同一坐标映射到多个输出位置（正常拼接不会发生）
    monkeypatch.setattr(
        reviser,
        "assemble",
        lambda segs: {
            "text": "甲乙",
            "sources": [
                [{"segment": 0, "pos": 0}],
                [{"segment": 0, "pos": 0}, {"segment": 1, "pos": 0}],
            ],
        },
    )
    with pytest.raises(RevisionError, match="多个输出位置"):
        reviser.revise(["甲乙", "丙丁"], [{"segment": 0, "pos": 0, "char": "甲"}])


def test_no_partial_revision_on_conflict():
    # 前一项校订合法、后一组冲突：整体失败，不返回任何修订结果
    edits = [
        {"segment": 2, "pos": 2, "char": "而"},   # 合法：位置 6
        {"segment": 0, "pos": 2, "char": "時"},   # 与下一项冲突
        {"segment": 1, "pos": 0, "char": "明"},
    ]
    with pytest.raises(RevisionConflictError):
        revise(SEGMENTS, edits)


def test_no_partial_revision_on_late_out_of_range():
    edits = [
        {"segment": 2, "pos": 2, "char": "而"},   # 合法
        {"segment": 9, "pos": 0, "char": "甲"},   # 越界
    ]
    with pytest.raises(RevisionError):
        revise(SEGMENTS, edits)


def test_empty_edits_returns_assembled_text():
    r = revise(SEGMENTS, [])
    assert r["text"] == "学而时习之不亦乐乎"
    assert r["changes"] == []
    assert r["sources"] == assemble(SEGMENTS)["sources"]


def test_edit_to_same_char_recorded():
    # 改字与原字相同仍记录为一处修订（from == to）
    r = revise(SEGMENTS, [{"segment": 2, "pos": 2, "char": "亦"}])
    assert r["text"] == "学而时习之不亦乐乎"
    assert r["changes"][0]["from"] == r["changes"][0]["to"] == "亦"


def test_changes_sorted_by_position_regardless_of_input_order():
    edits = [
        {"segment": 2, "pos": 3, "char": "哀"},   # 位置 7（乐）
        {"segment": 0, "pos": 0, "char": "教"},   # 位置 0（学）
    ]
    r = revise(SEGMENTS, edits)
    assert r["text"] == "教而时习之不亦哀乎"
    assert [c["pos"] for c in r["changes"]] == [0, 7]
    assert r["changes"][0]["from"] == "学" and r["changes"][0]["to"] == "教"
    assert r["changes"][1]["from"] == "乐" and r["changes"][1]["to"] == "哀"


def test_gate_failure_propagates_assembly_error():
    with pytest.raises(AssemblyError) as exc:
        revise(["孔子曰未知", "未知生焉", "完全无关文本"], [])
    assert exc.value.failed_segment == 2

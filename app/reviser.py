"""人工校订：按原始段坐标改写拼接文本。

复用 :func:`app.assembler.assemble` 的拼接文本与逐字来源，把每项校订
（段序号 ``segment``、原文下标 ``pos``、替换字 ``char``）经逐字来源定位到
最终文本中的唯一输出位置后改写，**不重新对齐**：

- 段序号或原文下标越界、坐标未映射到任何输出位置、或映射到多个输出位置，
  均抛出 :class:`RevisionError`（接口层转为 422）；
- 多项校订（重叠段的来源坐标）指向同一输出位置时，改字相同则合并为一处
  修改；改字不同则抛出 :class:`RevisionConflictError`（接口层转为 409），
  携带全部冲突位置与校订项；
- 任一环节失败都不产生部分修订；未涉及的输出位置保持原字。
"""

from __future__ import annotations

from .assembler import assemble


class RevisionError(ValueError):
    """校订坐标越界，或无法定位到唯一输出位置。"""


class RevisionConflictError(ValueError):
    """同一输出位置被多项校订指向且改字不一致。"""

    def __init__(self, conflicts: list[dict]):
        self.conflicts = conflicts
        positions = "、".join(str(c["pos"]) for c in conflicts)
        super().__init__(
            f"输出位置 {positions} 收到不一致的校订改字，无法确定修订结果"
        )


def _locate(sources: list[list[dict]], segment: int, pos: int) -> list[int]:
    """返回坐标 (segment, pos) 经逐字来源映射到的全部输出位置（升序）。"""
    return [
        out_pos
        for out_pos, srcs in enumerate(sources)
        if any(s["segment"] == segment and s["pos"] == pos for s in srcs)
    ]


def revise(segments: list[str], edits: list[dict]) -> dict:
    """先拼接 2～5 段转写再应用人工校订。

    返回 ``{"text": 修订后文本, "sources": 逐字来源, "changes": 逐位置修订记录}``；
    ``changes`` 按输出位置升序，每项含原字 ``from``、新字 ``to`` 与关联校订项
    ``edits``（指向同一位置且改字相同者已合并）。拼接阶段沿用 :func:`assemble`
    的续接门槛，失败时原样抛出 :class:`~app.assembler.AssemblyError`；校订阶段
    抛出 :class:`RevisionError` / :class:`RevisionConflictError`，均不产生部分
    修订。
    """
    result = assemble(segments)
    text, sources = result["text"], result["sources"]

    # 坐标范围校验：段序号或下标越界即拒绝（422）
    for idx, e in enumerate(edits):
        seg, pos = e["segment"], e["pos"]
        if not 0 <= seg < len(segments):
            raise RevisionError(
                f"第 {idx + 1} 项校订的段序号 {seg} 越界（共 {len(segments)} 段）"
            )
        if not 0 <= pos < len(segments[seg]):
            raise RevisionError(
                f"第 {idx + 1} 项校订的下标 {pos} 越界"
                f"（段 {seg} 共 {len(segments[seg])} 字）"
            )

    # 经逐字来源把每项校订定位到唯一输出位置
    located: list[tuple[int, dict]] = []
    for idx, e in enumerate(edits):
        hits = _locate(sources, e["segment"], e["pos"])
        if not hits:
            raise RevisionError(
                f"第 {idx + 1} 项校订（段 {e['segment']} 下标 {e['pos']}）"
                "未映射到任何输出位置"
            )
        if len(hits) > 1:
            raise RevisionError(
                f"第 {idx + 1} 项校订（段 {e['segment']} 下标 {e['pos']}）"
                f"映射到多个输出位置 {hits}，无法唯一确定改写位置"
            )
        located.append((hits[0], e))

    # 按输出位置归并：改字相同合并；不同则收集冲突（409）
    by_pos: dict[int, list[dict]] = {}
    for out_pos, e in located:
        by_pos.setdefault(out_pos, []).append(e)
    conflicts = [
        {"pos": out_pos, "edits": group}
        for out_pos, group in sorted(by_pos.items())
        if len({e["char"] for e in group}) > 1
    ]
    if conflicts:
        raise RevisionConflictError(conflicts)

    # 以上校验全部通过后才改写：任一失败都不产生部分修订
    chars = list(text)
    changes: list[dict] = []
    for out_pos, group in sorted(by_pos.items()):
        changes.append({
            "pos": out_pos,
            "from": chars[out_pos],
            "to": group[0]["char"],
            "edits": group,
        })
        chars[out_pos] = group[0]["char"]

    return {"text": "".join(chars), "sources": sources, "changes": changes}

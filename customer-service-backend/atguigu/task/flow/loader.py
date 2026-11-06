"""
流程加载器

一条链路：YAML 文件 -> Python dict -> 数据模型对象

load(path)        加载单个 yml
load_many(paths)  合并多个 yml（并检测重复槽位）
"""

from pathlib import Path
from typing import Any

import yaml

from atguigu.task.flow.flows import Flow, FlowsList, FlowSlot
from atguigu.task.flow.steps import CollectFlowStep, FlowStep


class FlowLoader:
    """
    流程加载器
    """

    def load_many(self, paths: list[Path]) -> FlowsList:
        """
        加载多个 yml，并合并为一份 FlowsList
        """
        flows: list[Flow] = []
        slots: dict[str, FlowSlot] = {}

        for path in paths:
            # 1. 加载单个文件
            single_flows_list = self.load(path)

            # 2. 流程直接累加
            flows.extend(single_flows_list.flows)

            # 3. 跨文件重复槽位检测：在加载期就失败，而不是运行时被悄悄覆盖
            duplicate_slot_names = set(slots).intersection(single_flows_list.slots)
            if duplicate_slot_names:
                duplicates = "、".join(sorted(duplicate_slot_names))
                raise ValueError(f"flow 定义中存在重复的槽位名称: {duplicates}.")

            # 4. 合并槽位
            slots.update(single_flows_list.slots)

        return FlowsList(flows=flows, slots=slots)

    def load(self, path: Path) -> FlowsList:
        """
        加载单个 yml 文件
        """
        # 1. 读 YAML -> dict
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        # 2. 先加载 slots（后面的 flows 要用它）
        slots: dict[str, FlowSlot] = self._load_slots(data.get("slots", {}))

        # 3. 再加载 flows
        flows: list[Flow] = self._load_flows(data.get("flows", {}), slots)

        return FlowsList(slots=slots, flows=flows)

    def _load_slots(self, yaml_slots_data: dict[str, Any]) -> dict[str, FlowSlot]:
        """
        解析 slots 块：YAML 的 key 就是槽位名，不在 value 里
        """
        slots = {}
        for slot_name, slot_dict in yaml_slots_data.items():
            slots[slot_name] = FlowSlot(name=slot_name, **slot_dict)

        return slots

    def _load_flows(self, yaml_flows_data: dict[str, Any], slots_definition: dict[str, FlowSlot]) -> list[Flow]:
        """
        解析 flows 块：每个流程的每个 step 走一次多态分发
        """
        flows: list[Flow] = []
        for flow_id, flow_dict in yaml_flows_data.items():
            steps = [FlowStep.from_dict(step) for step in flow_dict.get("steps", [])]
            flows.append(
                Flow(
                    id=flow_id,
                    description=flow_dict.get("description", ""),
                    name=flow_dict.get("name"),
                    steps=steps,
                    slots=self._collect_flow_slots(slots_definition, steps),
                )
            )

        return flows

    def _collect_flow_slots(self, slots_definition: dict[str, FlowSlot], steps: list[FlowStep]) -> list[FlowSlot]:
        """
        挑出当前流程真正用到的槽位

        只看 collect 步骤；同一槽位只保留一份；查不到定义就跳过不报错
        """
        seen = set()
        flow_slots = []

        for step in steps:
            # 只看收集步骤
            if not isinstance(step, CollectFlowStep):
                continue

            step_slot_name = step.slot_name

            # 去重：同一流程里重复收集同一个槽位，只留一份
            if step_slot_name in seen:
                continue
            seen.add(step_slot_name)

            # 用 get 查，查不到不报错
            slot_definition = slots_definition.get(step_slot_name)
            if slot_definition is not None:
                flow_slots.append(slot_definition)

        return flow_slots


if __name__ == "__main__":
    base_path = Path(__file__).parents[3]
    user_flow_path = base_path / "flow_config" / "user_flows.yml"
    system_flow_path = base_path / "flow_config" / "system_flows.yml"

    loader = FlowLoader()
    flows_list = loader.load_many([user_flow_path, system_flow_path])

    print(f"共加载 {len(flows_list.flows)} 个流程、{len(flows_list.slots)} 个槽位")
    for flow in flows_list.flows:
        print(f"- {flow.id:<32} steps={len(flow.steps):<2} slots={[s.name for s in flow.slots]}")

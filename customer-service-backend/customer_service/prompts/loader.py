# customer_service/prompts/loader.py

"""
提示词加载器：把 jinja2 模板文件读成字符串
"""

from pathlib import Path


def load_prompt(prompt_file_name: str) -> str:
    """
    按模板名读取对应文件的内容
    :param prompt_file_name: 模板文件名（不带 .jinja2 后缀）
    :return: 模板字符串
    """
    prompt_file_path = Path(__file__).resolve().parents[0] / "jinja2" / f"{prompt_file_name}.jinja2"
    return prompt_file_path.read_text(encoding="utf-8")


if __name__ == "__main__":
    print(load_prompt("turn_plan"))

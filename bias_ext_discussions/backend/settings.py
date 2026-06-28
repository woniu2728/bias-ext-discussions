from bias_core.extensions import setting_field


def setting_field_definitions():
    return (
        setting_field({
            "key": "allow_renaming",
            "label": "作者可重命名讨论",
            "type": "select",
            "default": "reply",
            "help_text": "控制讨论作者在发布后是否仍可修改标题。",
            "order": 10,
            "options": (
                {"value": "reply", "label": "无人回复前"},
                {"value": "-1", "label": "始终允许"},
                {"value": "0", "label": "不允许"},
                {"value": "10", "label": "10 分钟内"},
                {"value": "60", "label": "1 小时内"},
            ),
        }),
    )

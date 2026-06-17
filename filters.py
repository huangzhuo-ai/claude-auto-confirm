"""
高级过滤规则引擎：支持正则表达式匹配窗口标题、基于屏幕内容关键词过滤。
规则有优先级排序，支持启用/禁用开关。与 monitor.process() 集成。
"""
import re
from typing import Literal
from applog import log


FilterAction = Literal['auto', 'notify', 'ignore']


class FilterRule:
    """单条过滤规则。"""

    def __init__(self, rule_id: str, enabled: bool, rule_type: str,
                 pattern: str, action: FilterAction, priority: int = 0,
                 keywords: list[str] = None):
        """
        rule_id: 规则唯一标识（用于编辑/删除）
        enabled: 是否启用
        rule_type: 'title_regex' | 'content_contains'
        pattern: 正则表达式（title_regex 用）
        action: 'auto' | 'notify' | 'ignore'
        priority: 优先级（数字越小越优先，0 最高）
        keywords: 关键词列表（content_contains 用）
        """
        self.id = rule_id
        self.enabled = enabled
        self.type = rule_type
        self.pattern = pattern
        self.action = action
        self.priority = priority
        self.keywords = keywords or []

        # 编译正则表达式（title_regex）
        self._regex = None
        if rule_type == 'title_regex' and pattern:
            try:
                self._regex = re.compile(pattern, re.IGNORECASE)
            except Exception as e:
                log(f'[filters] 规则 {rule_id} 正则无效: {e}')
                self.enabled = False  # 无效规则自动禁用

    def matches(self, window_title: str, screen_text: str) -> bool:
        """判断该规则是否匹配给定的窗口和屏幕文本。"""
        if not self.enabled:
            return False

        if self.type == 'title_regex':
            return self._regex and self._regex.search(window_title) is not None
        elif self.type == 'content_contains':
            # 任一关键词在屏幕文本中出现即匹配（大小写不敏感）
            lower_text = screen_text.lower()
            return any(kw.lower() in lower_text for kw in self.keywords if kw)
        return False


class FilterEngine:
    """过滤规则引擎。管理多条规则，按优先级匹配。"""

    def __init__(self):
        self.rules: list[FilterRule] = []

    def add_rule(self, rule: FilterRule):
        """添加一条规则。"""
        self.rules.append(rule)
        self._sort_rules()

    def remove_rule(self, rule_id: str) -> bool:
        """删除规则。返回是否成功。"""
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < before

    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """更新规则属性（enabled, priority, pattern 等）。返回是否找到规则。"""
        for r in self.rules:
            if r.id == rule_id:
                for k, v in kwargs.items():
                    if hasattr(r, k):
                        setattr(r, k, v)
                # 如果更新了 pattern，重新编译正则
                if 'pattern' in kwargs and r.type == 'title_regex':
                    try:
                        r._regex = re.compile(r.pattern, re.IGNORECASE)
                    except Exception as e:
                        log(f'[filters] 规则 {rule_id} 正则无效: {e}')
                        r.enabled = False
                self._sort_rules()
                return True
        return False

    def get_rule(self, rule_id: str) -> FilterRule | None:
        """获取规则。"""
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    def clear_rules(self):
        """清空所有规则。"""
        self.rules.clear()

    def match(self, window_title: str, screen_text: str) -> FilterAction | None:
        """匹配规则，返回第一个匹配的规则的动作。无匹配返回 None（回退到默认策略）。
        规则按优先级排序，越小越优先。"""
        for rule in self.rules:
            if rule.matches(window_title, screen_text):
                log(f'[filters] 规则 {rule.id} 匹配，动作: {rule.action}')
                return rule.action
        return None

    def _sort_rules(self):
        """按优先级排序（priority 越小越靠前）。"""
        self.rules.sort(key=lambda r: r.priority)

    def to_dict_list(self) -> list[dict]:
        """导出规则列表为字典（供 config 序列化）。"""
        return [
            {
                'id': r.id,
                'enabled': r.enabled,
                'type': r.type,
                'pattern': r.pattern,
                'action': r.action,
                'priority': r.priority,
                'keywords': r.keywords,
            }
            for r in self.rules
        ]

    def from_dict_list(self, rules_data: list[dict]):
        """从字典列表加载规则（config 反序列化）。"""
        self.rules.clear()
        for rd in rules_data:
            try:
                rule = FilterRule(
                    rule_id=rd.get('id', ''),
                    enabled=rd.get('enabled', True),
                    rule_type=rd.get('type', 'title_regex'),
                    pattern=rd.get('pattern', ''),
                    action=rd.get('action', 'auto'),
                    priority=rd.get('priority', 0),
                    keywords=rd.get('keywords', []),
                )
                self.rules.append(rule)
            except Exception as e:
                log(f'[filters] 加载规则失败: {e}')
        self._sort_rules()


# 全局单例（monitor.process() 调用）
_engine = FilterEngine()


def match(window_title: str, screen_text: str) -> FilterAction | None:
    """全局匹配函数，供 monitor.process() 调用。"""
    return _engine.match(window_title, screen_text)


def add_rule(rule: FilterRule):
    """添加规则。"""
    _engine.add_rule(rule)


def remove_rule(rule_id: str) -> bool:
    """删除规则。"""
    return _engine.remove_rule(rule_id)


def update_rule(rule_id: str, **kwargs) -> bool:
    """更新规则。"""
    return _engine.update_rule(rule_id, **kwargs)


def get_rule(rule_id: str) -> FilterRule | None:
    """获取规则。"""
    return _engine.get_rule(rule_id)


def clear_rules():
    """清空所有规则。"""
    _engine.clear_rules()


def list_rules() -> list[FilterRule]:
    """列出所有规则（按优先级排序）。"""
    return _engine.rules.copy()


def load_from_config(cfg: dict):
    """从配置加载规则。cfg 是 config.load() 的返回值。"""
    rules_data = cfg.get('filters', [])
    if isinstance(rules_data, list):
        _engine.from_dict_list(rules_data)


def save_to_config(cfg: dict):
    """把规则保存到配置字典。调用者需要调用 config.save(cfg)。"""
    cfg['filters'] = _engine.to_dict_list()

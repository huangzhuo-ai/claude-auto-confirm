"""filters.py 单元测试：高级过滤规则的匹配、优先级、管理。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import filters


@pytest.fixture(autouse=True)
def reset_engine():
    """每个测试前清空规则引擎。"""
    filters.clear_rules()
    yield
    filters.clear_rules()


def test_title_regex_match():
    """标题正则匹配。"""
    rule = filters.FilterRule('r1', True, 'title_regex', r'.*test.*', 'notify')
    filters.add_rule(rule)
    assert filters.match('my test window', '') == 'notify'
    assert filters.match('production', '') is None


def test_content_contains_match():
    """内容关键词匹配。"""
    rule = filters.FilterRule('r2', True, 'content_contains', '', 'ignore',
                             keywords=['deploy', 'production'])
    filters.add_rule(rule)
    assert filters.match('any title', 'deploying to production') == 'ignore'
    assert filters.match('any title', 'local dev') is None


def test_priority_order():
    """优先级排序：数字越小越优先。"""
    r1 = filters.FilterRule('r1', True, 'title_regex', r'.*', 'auto', priority=10)
    r2 = filters.FilterRule('r2', True, 'title_regex', r'.*test.*', 'notify', priority=1)
    filters.add_rule(r1)
    filters.add_rule(r2)
    # r2 优先级更高（1 < 10），应先匹配
    assert filters.match('test window', '') == 'notify'


def test_disabled_rule_no_match():
    """禁用的规则不匹配。"""
    rule = filters.FilterRule('r3', False, 'title_regex', r'.*', 'ignore')
    filters.add_rule(rule)
    assert filters.match('any title', '') is None


def test_invalid_regex_auto_disabled():
    """无效正则自动禁用规则。"""
    rule = filters.FilterRule('r4', True, 'title_regex', r'[invalid(', 'notify')
    assert not rule.enabled  # 构造时已检测无效，自动禁用


def test_update_rule():
    """更新规则属性。"""
    rule = filters.FilterRule('r5', True, 'title_regex', r'old', 'auto')
    filters.add_rule(rule)
    filters.update_rule('r5', pattern=r'new', action='notify')
    updated = filters.get_rule('r5')
    assert updated.pattern == r'new'
    assert updated.action == 'notify'


def test_remove_rule():
    """删除规则。"""
    rule = filters.FilterRule('r6', True, 'title_regex', r'.*', 'auto')
    filters.add_rule(rule)
    assert filters.remove_rule('r6')
    assert filters.get_rule('r6') is None


def test_to_dict_list():
    """导出为字典列表（供配置序列化）。"""
    r1 = filters.FilterRule('r7', True, 'title_regex', r'test', 'notify', priority=5)
    filters.add_rule(r1)
    data = filters._engine.to_dict_list()
    assert len(data) == 1
    assert data[0]['id'] == 'r7'
    assert data[0]['pattern'] == r'test'


def test_from_dict_list():
    """从字典列表加载规则。"""
    data = [
        {'id': 'r8', 'enabled': True, 'type': 'title_regex',
         'pattern': r'prod', 'action': 'notify', 'priority': 0, 'keywords': []},
    ]
    filters._engine.from_dict_list(data)
    assert len(filters.list_rules()) == 1
    assert filters.match('production window', '') == 'notify'


def test_case_insensitive():
    """标题正则和关键词匹配都大小写不敏感。"""
    r1 = filters.FilterRule('r9', True, 'title_regex', r'Test', 'notify')
    r2 = filters.FilterRule('r10', True, 'content_contains', '', 'ignore',
                           keywords=['ERROR'])
    filters.add_rule(r1)
    filters.add_rule(r2)
    assert filters.match('test window', '') == 'notify'
    assert filters.match('any', 'error occurred') == 'ignore'

"""统计报告生成模块：生成周报/月报，导出为Markdown或HTML。

功能：
- 生成周报（最近7天）
- 生成月报（最近30天）
- 导出为Markdown格式
- 导出为HTML格式（带图表和样式）
- 计算节省时间
- 统计活跃终端Top N
- 统计活跃时段
"""
from datetime import datetime, timedelta
import state
from pathlib import Path


def generate_report(days=7, format='markdown'):
    """生成统计报告。

    Args:
        days: 统计天数（7=周报, 30=月报）
        format: 输出格式（'markdown' 或 'html'）

    Returns:
        str: 报告内容
    """
    if format == 'markdown':
        return _generate_markdown_report(days)
    elif format == 'html':
        return _generate_html_report(days)
    else:
        raise ValueError(f'不支持的格式: {format}')


def _generate_markdown_report(days):
    """生成Markdown格式报告。"""
    # 获取日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days-1)
    period = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"

    # 标题
    report_type = '周报' if days == 7 else '月报'
    lines = [
        f"# Claude Auto-Yes {report_type} ({period})",
        "",
    ]

    # 获取历史数据
    hist = state.get_daily_history(days=days)

    # 计算总数
    total_auto = sum(d.get('auto_yes', 0) for d in hist)
    total_notify = sum(d.get('notify', 0) for d in hist)
    total_error = sum(d.get('error', 0) for d in hist)
    total_idle = sum(d.get('idle', 0) for d in hist)

    # 节省时间估算（每次2秒）
    saved_seconds = total_auto * 2
    saved_minutes = saved_seconds / 60

    # 概览
    lines.extend([
        "## 📊 概览",
        "",
        f"- 总确认次数: **{total_auto}**",
        f"- 节省时间估算: **{saved_minutes:.1f}分钟**（按2秒/次计算）",
        f"- 通知次数: {total_notify}",
        f"- 错误通知: {total_error}",
        f"- 空闲提醒: {total_idle}",
        "",
    ])

    # 每日趋势
    lines.extend([
        "## 📈 每日趋势",
        "",
        "| 日期 | 自动确认 | 通知 | 错误 | 空闲 |",
        "|------|----------|------|------|------|",
    ])

    for d in reversed(hist):
        date = d.get('date', '')
        auto = d.get('auto_yes', 0)
        notify = d.get('notify', 0)
        error = d.get('error', 0)
        idle = d.get('idle', 0)
        lines.append(f"| {date} | {auto} | {notify} | {error} | {idle} |")

    lines.append("")

    # 活跃终端 Top 5
    window_stats = state.get_window_stats()
    if window_stats:
        window_totals = [
            (win, stats.get('auto_yes', 0) + stats.get('notify', 0) +
             stats.get('error', 0) + stats.get('idle', 0))
            for win, stats in window_stats.items()
        ]
        window_totals.sort(key=lambda x: x[1], reverse=True)
        top_windows = window_totals[:5]

        lines.extend([
            "## 🖥️ 活跃终端 Top 5",
            "",
        ])

        for idx, (win, count) in enumerate(top_windows, 1):
            auto = window_stats[win].get('auto_yes', 0)
            lines.append(f"{idx}. **{win}** - {count}次（自动确认: {auto}）")

        lines.append("")

    # 活跃时段
    hourly_stats = state.get_hourly_stats()
    if hourly_stats:
        hour_totals = {}
        for hour_str, stats in hourly_stats.items():
            total = (stats.get('auto_yes', 0) + stats.get('notify', 0) +
                     stats.get('error', 0) + stats.get('idle', 0))
            hour_totals[hour_str] = total

        if hour_totals:
            max_hour = max(hour_totals.items(), key=lambda x: x[1])
            min_hour = min((h, c) for h, c in hour_totals.items() if c > 0)

            lines.extend([
                "## ⏰ 活跃时段",
                "",
                f"- 最活跃: **{max_hour[0]}:00-{max_hour[0]}:59** ({max_hour[1]}次)",
                f"- 最安静: **{min_hour[0]}:00-{min_hour[0]}:59** ({min_hour[1]}次)",
                "",
            ])

    # 本周/月亮点
    if hist:
        # 找到确认次数最多的一天
        max_day = max(hist, key=lambda d: d.get('auto_yes', 0))
        max_date = max_day.get('date', '')
        max_count = max_day.get('auto_yes', 0)

        # 找到无打扰的时段
        quiet_hours = [h for h, c in hour_totals.items() if c == 0] if hourly_stats else []

        lines.extend([
            f"## 💡 {report_type}亮点",
            "",
        ])

        if max_count > 0:
            weekday = datetime.strptime(max_date, '%Y-%m-%d').strftime('%A')
            weekday_cn = {'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
                          'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六',
                          'Sunday': '星期日'}
            lines.append(f"- {weekday_cn.get(weekday, weekday)}（{max_date}）确认次数最多：**{max_count}次**")

        if quiet_hours:
            lines.append(f"- 静默时段工作正常，{len(quiet_hours)}小时无打扰")

        if total_error == 0:
            lines.append("- 运行稳定，无错误通知 ✅")

        lines.append("")

    # 生成时间
    lines.extend([
        "---",
        "",
        f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    return '\n'.join(lines)


def _generate_html_report(days):
    """生成HTML格式报告。"""
    md_content = _generate_markdown_report(days)

    # 简单的Markdown to HTML转换
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="zh-CN">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Claude Auto-Yes 统计报告</title>')
    html_lines.append('    <style>')
    html_lines.append('        body { font-family: "Segoe UI", Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; background: #f5f5f5; }')
    html_lines.append('        .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }')
    html_lines.append('        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }')
    html_lines.append('        h2 { color: #34495e; margin-top: 30px; border-left: 4px solid #3498db; padding-left: 10px; }')
    html_lines.append('        table { width: 100%; border-collapse: collapse; margin: 20px 0; }')
    html_lines.append('        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }')
    html_lines.append('        th { background: #3498db; color: white; }')
    html_lines.append('        tr:hover { background: #f5f5f5; }')
    html_lines.append('        ul, ol { line-height: 1.8; }')
    html_lines.append('        strong { color: #e74c3c; }')
    html_lines.append('        hr { margin: 30px 0; border: none; border-top: 1px solid #ddd; }')
    html_lines.append('        .footer { text-align: center; color: #7f8c8d; font-size: 0.9em; margin-top: 30px; }')
    html_lines.append('    </style>')
    html_lines.append('</head>')
    html_lines.append('<body>')
    html_lines.append('    <div class="container">')

    # 转换Markdown内容为HTML
    in_table = False
    in_list = False
    for line in md_content.split('\n'):
        line = line.strip()

        if not line:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append('<br>')
            continue

        # 标题
        if line.startswith('# '):
            html_lines.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '):
            if in_table:
                html_lines.append('</table>')
                in_table = False
            html_lines.append(f'<h2>{line[3:]}</h2>')

        # 表格
        elif line.startswith('|'):
            if not in_table:
                html_lines.append('<table>')
                in_table = True

            cells = [c.strip() for c in line.split('|')[1:-1]]
            if '---' in line:
                continue  # 跳过表格分隔行
            elif line.startswith('| 日期'):
                # 表头
                html_lines.append('<tr>')
                for cell in cells:
                    html_lines.append(f'<th>{cell}</th>')
                html_lines.append('</tr>')
            else:
                # 表格行
                html_lines.append('<tr>')
                for cell in cells:
                    html_lines.append(f'<td>{cell}</td>')
                html_lines.append('</tr>')

        # 列表
        elif line.startswith('- '):
            if in_table:
                html_lines.append('</table>')
                in_table = False
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            # 处理粗体
            content = line[2:].replace('**', '<strong>').replace('**', '</strong>')
            html_lines.append(f'<li>{content}</li>')

        elif line.startswith(('1.', '2.', '3.', '4.', '5.')):
            if in_table:
                html_lines.append('</table>')
                in_table = False
            if not in_list:
                html_lines.append('<ol>')
                in_list = True
            # 处理粗体
            content = line.split('. ', 1)[1].replace('**', '<strong>').replace('**', '</strong>')
            html_lines.append(f'<li>{content}</li>')

        # 分隔线
        elif line.startswith('---'):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            if in_table:
                html_lines.append('</table>')
                in_table = False
            html_lines.append('<hr>')

        # 普通段落
        elif line.startswith('*') and line.endswith('*'):
            html_lines.append(f'<p class="footer">{line[1:-1]}</p>')
        else:
            html_lines.append(f'<p>{line}</p>')

    if in_list:
        html_lines.append('</ul>')
    if in_table:
        html_lines.append('</table>')

    html_lines.append('    </div>')
    html_lines.append('</body>')
    html_lines.append('</html>')

    return '\n'.join(html_lines)


def save_report(content, filename=None, format='markdown'):
    """保存报告到文件。

    Args:
        content: 报告内容
        filename: 文件名（None则自动生成）
        format: 格式（'markdown' 或 'html'）

    Returns:
        str: 保存的文件路径
    """
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        ext = 'md' if format == 'markdown' else 'html'
        filename = f'report_{timestamp}.{ext}'

    filepath = Path(filename)
    filepath.write_text(content, encoding='utf-8')

    return str(filepath)

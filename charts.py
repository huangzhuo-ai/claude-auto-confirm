"""图表生成模块：使用matplotlib生成统计图表，嵌入到CustomTkinter面板。

提供的图表类型：
- 30天趋势折线图
- 动作分布饼图
- 按窗口统计横向条形图
- 按小时统计热力图
"""
import matplotlib
matplotlib.use('Agg')  # 无GUI后端
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
from datetime import datetime, timedelta
import state


# 中文字体配置（Windows环境）
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


def create_trend_chart(parent_frame, days=30):
    """创建趋势折线图（最近N天的自动确认趋势）

    Args:
        parent_frame: CustomTkinter父容器
        days: 显示天数（默认30天）

    Returns:
        FigureCanvasTkAgg对象（已pack到父容器）
    """
    fig = Figure(figsize=(8, 3), dpi=100, facecolor='#2b2b2b')
    ax = fig.add_subplot(111)

    # 获取历史数据
    hist = state.get_daily_history(days=days)

    # 如果数据不足days天，补充空数据
    if len(hist) < days:
        # 计算需要补充的日期
        if hist:
            last_date = datetime.strptime(hist[0]['date'], '%Y-%m-%d')
        else:
            last_date = datetime.now()

        all_data = []
        for i in range(days):
            date = (last_date - timedelta(days=days-1-i)).strftime('%Y-%m-%d')
            # 查找该日期的数据
            day_data = next((d for d in hist if d['date'] == date), None)
            if day_data:
                all_data.append(day_data)
            else:
                all_data.append({'date': date, 'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0})
        hist = all_data
    else:
        hist = list(reversed(hist[:days]))  # 倒序：最老在左，最新在右

    # 提取数据
    dates = [d['date'][-5:] for d in hist]  # 只显示MM-DD
    auto_yes = [d.get('auto_yes', 0) for d in hist]
    notify = [d.get('notify', 0) for d in hist]
    error = [d.get('error', 0) for d in hist]
    idle = [d.get('idle', 0) for d in hist]

    # 绘制多条折线
    ax.plot(dates, auto_yes, marker='o', label='自动确认', color='#4CAF50', linewidth=2)
    ax.plot(dates, notify, marker='s', label='通知', color='#FFC107', linewidth=1.5)
    ax.plot(dates, error, marker='^', label='错误', color='#F44336', linewidth=1.5)
    ax.plot(dates, idle, marker='d', label='空闲', color='#FF9800', linewidth=1.5)

    # 样式设置
    ax.set_facecolor('#1e1e1e')
    ax.set_title(f'最近{days}天趋势', color='white', fontsize=12, pad=10)
    ax.set_xlabel('日期', color='gray', fontsize=9)
    ax.set_ylabel('次数', color='gray', fontsize=9)
    ax.tick_params(colors='gray', labelsize=8)
    ax.grid(True, alpha=0.2, color='gray', linestyle='--')
    ax.legend(loc='upper left', fontsize=8, framealpha=0.8)

    # 只显示部分日期标签（避免拥挤）
    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=45)

    fig.tight_layout()

    # 嵌入到CustomTkinter
    canvas = FigureCanvasTkAgg(fig, master=parent_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True)

    return canvas


def create_distribution_pie(parent_frame):
    """创建动作分布饼图（累计统计的占比）

    Args:
        parent_frame: CustomTkinter父容器

    Returns:
        FigureCanvasTkAgg对象
    """
    fig = Figure(figsize=(4, 3), dpi=100, facecolor='#2b2b2b')
    ax = fig.add_subplot(111)

    # 获取累计统计
    data = state.load()
    total = data.get('counters', {}).get('total', {})
    auto_yes = total.get('auto_yes', 0)
    notify = total.get('notify', 0)
    error = total.get('error', 0)
    idle = total.get('idle', 0)

    # 数据和标签
    values = [auto_yes, notify, error, idle]
    labels = ['自动确认', '通知', '错误', '空闲']
    colors = ['#4CAF50', '#FFC107', '#F44336', '#FF9800']

    # 过滤掉为0的项
    filtered = [(v, l, c) for v, l, c in zip(values, labels, colors) if v > 0]
    if not filtered:
        # 没有数据时显示提示
        ax.text(0.5, 0.5, '暂无数据', ha='center', va='center',
                fontsize=14, color='gray', transform=ax.transAxes)
        ax.set_facecolor('#1e1e1e')
        ax.axis('off')
    else:
        values, labels, colors = zip(*filtered)

        # 绘制饼图
        wedges, texts, autotexts = ax.pie(
            values, labels=labels, colors=colors,
            autopct='%1.1f%%', startangle=90,
            textprops={'color': 'white', 'fontsize': 9}
        )

        # 设置百分比文字样式
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(8)
            autotext.set_weight('bold')

        ax.set_facecolor('#1e1e1e')

    ax.set_title('动作分布', color='white', fontsize=12, pad=10)
    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=parent_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True)

    return canvas


def create_window_bar_chart(parent_frame, top_n=10):
    """创建按窗口统计的横向条形图（Top N活跃窗口）

    Args:
        parent_frame: CustomTkinter父容器
        top_n: 显示前N个窗口

    Returns:
        FigureCanvasTkAgg对象
    """
    fig = Figure(figsize=(6, 4), dpi=100, facecolor='#2b2b2b')
    ax = fig.add_subplot(111)

    # 获取按窗口统计
    window_stats = state.get_window_stats()

    if not window_stats:
        ax.text(0.5, 0.5, '暂无数据', ha='center', va='center',
                fontsize=14, color='gray', transform=ax.transAxes)
        ax.set_facecolor('#1e1e1e')
        ax.axis('off')
    else:
        # 计算每个窗口的总次数并排序
        window_totals = [
            (win, stats.get('auto_yes', 0) + stats.get('notify', 0) +
             stats.get('error', 0) + stats.get('idle', 0))
            for win, stats in window_stats.items()
        ]
        window_totals.sort(key=lambda x: x[1], reverse=True)
        top_windows = window_totals[:top_n]

        # 提取数据
        windows = [w[0][:30] for w in top_windows]  # 窗口名截断
        auto_yes = [window_stats[w[0]].get('auto_yes', 0) for w in top_windows]
        notify = [window_stats[w[0]].get('notify', 0) for w in top_windows]
        error = [window_stats[w[0]].get('error', 0) for w in top_windows]
        idle = [window_stats[w[0]].get('idle', 0) for w in top_windows]

        # 绘制堆叠横向条形图
        y_pos = range(len(windows))
        ax.barh(y_pos, auto_yes, label='自动确认', color='#4CAF50')
        ax.barh(y_pos, notify, left=auto_yes, label='通知', color='#FFC107')
        ax.barh(y_pos, error, left=[a+n for a, n in zip(auto_yes, notify)],
                label='错误', color='#F44336')
        ax.barh(y_pos, idle,
                left=[a+n+e for a, n, e in zip(auto_yes, notify, error)],
                label='空闲', color='#FF9800')

        # 样式设置
        ax.set_facecolor('#1e1e1e')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(windows, fontsize=8)
        ax.set_xlabel('次数', color='gray', fontsize=9)
        ax.set_title(f'Top {len(windows)} 活跃窗口', color='white', fontsize=12, pad=10)
        ax.tick_params(colors='gray', labelsize=8)
        ax.grid(True, alpha=0.2, color='gray', linestyle='--', axis='x')
        ax.legend(loc='lower right', fontsize=7, framealpha=0.8)

    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=parent_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True)

    return canvas


def create_hourly_heatmap(parent_frame):
    """创建按小时统计的热力图（24小时活动热度）

    Args:
        parent_frame: CustomTkinter父容器

    Returns:
        FigureCanvasTkAgg对象
    """
    fig = Figure(figsize=(8, 2), dpi=100, facecolor='#2b2b2b')
    ax = fig.add_subplot(111)

    # 获取按小时统计
    hourly_stats = state.get_hourly_stats()

    # 构建24小时数据（横轴）
    hours = [f'{h:02d}' for h in range(24)]
    totals = []
    for hour in hours:
        stats = hourly_stats.get(hour, {})
        total = (stats.get('auto_yes', 0) + stats.get('notify', 0) +
                 stats.get('error', 0) + stats.get('idle', 0))
        totals.append(total)

    # 绘制条形图（模拟热力图效果）
    colors = plt.cm.YlOrRd([t / max(totals) if totals and max(totals) > 0 else 0 for t in totals])
    ax.bar(hours, totals, color=colors, width=0.8)

    # 样式设置
    ax.set_facecolor('#1e1e1e')
    ax.set_title('24小时活动热力图', color='white', fontsize=12, pad=10)
    ax.set_xlabel('小时', color='gray', fontsize=9)
    ax.set_ylabel('次数', color='gray', fontsize=9)
    ax.tick_params(colors='gray', labelsize=7)
    ax.grid(True, alpha=0.2, color='gray', linestyle='--', axis='y')

    # 只显示部分小时标签
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([hours[i] for i in range(0, 24, 3)])

    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=parent_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True)

    return canvas

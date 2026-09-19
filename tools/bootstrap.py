"""Provision independent Feishu tables and dashboard, with resumable checkpoints."""
from pathlib import Path
from runtime import atomic_json, read_json

NODES = ['12小时', '24小时', '48小时', '72小时', '7天']
METRICS = ['播放量', '点赞数', '评论数', '分享数', '收藏数', '涨粉数', '主页访问', '平均播放时长（秒）', '完播率', '5秒完播率', '2秒跳出率', '封面点击率']


def text(name):
    return {'name': name, 'type': 'text'}


def select(name, options):
    hues = ['Blue', 'Green', 'Orange', 'Purple', 'Red', 'Gray', 'Carmine']
    return {'name': name, 'type': 'select', 'multiple': False,
            'options': [{'name': value, 'hue': hues[i % len(hues)], 'lightness': 'Light'} for i, value in enumerate(options)]}


def schemas():
    return {
        'content_table_id': ('内容项目', [text(n) for n in ['抖音作品ID', '视频标题', '作品链接', '发布时间', '当前复盘节点', '复盘结论', '下一步动作']] + [select('采集状态', ['待采集', '采集中', '待复盘', '已复盘', '已完成'])]),
        'snapshot_table_id': ('作品数据快照', [text(n) for n in ['快照键', '抖音作品ID', '快照名称', '采集节点', '计划采集时间', '实际采集时间', '数据完整度V2', '原始证据摘要', '最近错误']] +
            [select('执行状态', ['待采集', '成功', '延迟补采', '失败', '被阻塞', '已错过', '采集中'])] +
            [{'name': n, 'type': 'number', 'style': {'type': 'plain', 'precision': 2, 'percentage': n in ['完播率', '5秒完播率', '2秒跳出率', '封面点击率']}} for n in METRICS]),
        'comments_table_id': ('观众问题与回复草稿', [text(n) for n in ['评论键', '抖音作品ID', '原评论', '回复草稿', '来源', '采集时间']] + [select('状态', ['未发送草稿']), {'name': '模拟数据', 'type': 'checkbox'}]),
    }


def save_config(config):
    atomic_json(config['_path'], {k: v for k, v in config.items() if not k.startswith('_')})


def unique_resource(data, name, kind):
    items = data.get(kind, data.get('items', []))
    if data.get('has_more'):
        raise ValueError('RESOURCE_LIST_INCOMPLETE')
    found = [item for item in items if item.get('name') == name]
    if len(found) > 1:
        raise ValueError('DUPLICATE_RESOURCE_NAME')
    return found[0] if found else None


def resource_id(item, kind):
    result = item.get('id') or item.get(kind + '_id')
    if not isinstance(result, str) or not result:
        raise ValueError('RESOURCE_ID_MISSING')
    return result


def provision(config, api, name):
    root = Path(config['data_dir'])
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / 'bootstrap-checkpoint.json'
    state = read_json(checkpoint) if checkpoint.exists() else {}
    schema = schemas()
    if not config.get('base_token'):
        if state.get('base_creation_started'):
            raise ValueError('BASE_CREATE_UNCERTAIN: locate created Base and set base_token; do not create another')
        state['base_creation_started'] = True
        atomic_json(checkpoint, state)
        table_name, fields = schema['content_table_id']
        data = api.call('+base-create', name=name, table_name=table_name, fields=fields, time_zone='Asia/Shanghai')
        base = data.get('base', data)
        token = base.get('base_token') or base.get('token')
        if not token:
            raise ValueError('BASE_TOKEN_NOT_RETURNED')
        config['base_token'] = api.base = token
        save_config(config)
    api.base = config['base_token']
    for config_key, (table_name, fields) in schema.items():
        table = unique_resource(api.call('+table-list'), table_name, 'tables')
        if table is None:
            op = 'creating:' + table_name
            if state.get(op):
                raise ValueError('TABLE_CREATE_UNCERTAIN: inspect remote before retry')
            state[op] = True
            atomic_json(checkpoint, state)
            api.call('+table-create', name=table_name, fields=fields)
            table = unique_resource(api.call('+table-list'), table_name, 'tables')
            if table is None:
                raise ValueError('TABLE_CREATE_READBACK_MISSING')
        ident = resource_id(table, 'table')
        config[config_key] = ident
        save_config(config)
        actual = api.fields(ident)
        if {f['name'] for f in fields} - set(actual):
            raise ValueError('EXISTING_TABLE_SCHEMA_CONFLICT: use an empty dedicated Base')
    dashboard = unique_resource(api.call('+dashboard-list'), '作品复盘概览', 'dashboards')
    if dashboard is None:
        if state.get('dashboard_creation_started'):
            raise ValueError('DASHBOARD_CREATE_UNCERTAIN')
        state['dashboard_creation_started'] = True
        atomic_json(checkpoint, state)
        api.call('+dashboard-create', name='作品复盘概览')
        dashboard = unique_resource(api.call('+dashboard-list'), '作品复盘概览', 'dashboards')
    config['dashboard_id'] = resource_id(dashboard, 'dashboard')
    save_config(config)
    dash = config['dashboard_id']
    api.call('+dashboard-update', dashboard_id=dash, theme_style='futuristic')
    blocks = dashboard_blocks()
    for block_name, kind, data in blocks:
        exists = unique_resource(api.call('+dashboard-block-list', dashboard_id=dash), block_name, 'blocks')
        if exists:
            continue
        op = 'block:' + block_name
        if state.get(op):
            raise ValueError('BLOCK_CREATE_UNCERTAIN')
        state[op] = True
        atomic_json(checkpoint, state)
        api.call('+dashboard-block-create', dashboard_id=dash, name=block_name, type=kind, data_config=data)
    return {'ok': True, 'tables': len(schema), 'dashboard_blocks': len(blocks), 'theme': 'futuristic'}


def dashboard_blocks():
    blocks = [('阅读说明', 'text', {'text': '## 数据支持判断，不代替判断\n五节点累计数据不能相加。待复盘表示尚未完成分析，不表示尚未导出。比较图仅纳入准点72小时成功快照；延迟补采单独查看。'}),
              ('已登记作品数', 'statistics', {'table_name': '内容项目', 'count_all': True}),
              ('待复盘作品', 'statistics', {'table_name': '内容项目', 'count_all': True, 'filter': {'conjunction': 'and', 'conditions': [{'field_name': '采集状态', 'operator': 'is', 'value': '待复盘'}]}}),
              ('节点执行状态', 'ring', {'table_name': '作品数据快照', 'count_all': True, 'group_by': [{'field_name': '执行状态', 'mode': 'integrated'}]}),
              ('观众问题数', 'statistics', {'table_name': '观众问题与回复草稿', 'count_all': True})]
    for metric in ['播放量', '收藏数', '涨粉数', '5秒完播率']:
        blocks.append(('72小时' + metric, 'bar', {'table_name': '作品数据快照', 'series': [{'field_name': metric, 'rollup': 'MAX'}],
            'group_by': [{'field_name': '快照名称', 'mode': 'integrated'}],
            'filter': {'conjunction': 'and', 'conditions': [{'field_name': '采集节点', 'operator': 'is', 'value': '72小时'}, {'field_name': '执行状态', 'operator': 'is', 'value': '成功'}, {'field_name': metric, 'operator': 'isNotEmpty'}]}}))
    return blocks

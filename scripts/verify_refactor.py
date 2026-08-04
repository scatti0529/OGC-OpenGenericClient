# -*- coding: utf-8 -*-
"""验证重构：检查新架构中是否还有旧引用残留"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 旧模块引用
old_refs = [
    'ilbs.', 'OGClogin', 'OGChome', 'from Ui_LoginWindow',
    'from sqlit', 'import sqlit',
    'from app.', 'app.',
]
# 旧资源路径
old_paths = ['res/', 'res\\']

# 需要检查的文件
targets = []
for d in ['core', 'ui', 'pages', 'services']:
    targets.extend(list((ROOT / d).rglob('*.py')))
targets.append(ROOT / 'main.py')

print('=== 旧模块引用检查 ===')
found_ref = False
for f in targets:
    try:
        content = f.read_text(encoding='utf-8')
    except Exception:
        continue
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('//'):
            continue
        # 跳过文档字符串中的描述性文字
        for ref in old_refs:
            if ref in line:
                # 排除 docstring 中的示例
                if any(kw in line for kw in ['替代原', '提取至', '用法', '使用 ']):
                    continue
                print(f'{f.relative_to(ROOT)}:{i}: {line.strip()[:130]}')
                found_ref = True
                break
if not found_ref:
    print('✓ 新架构代码中无旧模块引用残留')

print()
print('=== 旧资源路径检查 ===')
found_path = False
for f in targets:
    try:
        content = f.read_text(encoding='utf-8')
    except Exception:
        continue
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('//'):
            continue
        # 检查是否还有 res/ 旧路径（但排除 resources/ 新路径）
        for ref in old_paths:
            if ref in line and 'resources/' not in line:
                print(f'{f.relative_to(ROOT)}:{i}: {line.strip()[:130]}')
                found_path = True
                break
if not found_path:
    print('✓ 新架构代码中无旧资源路径残留')

print()
print('=== 新架构资源引用确认 ===')
count = 0
for f in targets:
    try:
        content = f.read_text(encoding='utf-8')
    except Exception:
        continue
    if 'resources/' in content or 'resources\\' in content:
        count += 1
print(f'✓ 共 {count} 个文件使用了新的 resources/ 资源路径')

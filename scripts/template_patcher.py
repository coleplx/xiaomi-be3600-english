#!/usr/bin/env python3
"""
template_patcher.py - Find and wrap unwrapped Chinese strings in LuCI templates.
Scans .htm files, finds Chinese text outside <%: %> tags, wraps them.
Can operate on local files or remote router via SSH.
"""

import os
import re
import sys
import subprocess

CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')
# Match a run of Chinese-containing text that's not inside <%...%> or <script> tags
# We want text between HTML tags: >text< or attribute values
UNWRAPPED_HTML_RE = re.compile(
    r'(>)([^<]*?[\u4e00-\u9fff][^<]*?)(<)',
    re.DOTALL
)

# But skip if inside <%...%> block
# Also skip comments, script blocks, style blocks
SKIP_BLOCKS = [
    (r'<script[^>]*>.*?</script>', ''),
    (r'<!--.*?-->', ''),
    (r'<style[^>]*>.*?</style>', ''),
]

def find_unwrapped_chinese(content):
    """Find all Chinese text occurrences that are NOT inside <%:...%> tags."""
    # Remove already-wrapped strings
    # Replace <%:TEXT%> with placeholder
    wrapped_placeholders = []
    def replace_wrapped(m):
        wrapped_placeholders.append(m.group(0))
        return '___WRAPPED___'
    
    # Remove LuCI template blocks <% ... %>
    cleaned = re.sub(r'<%[^>]*%>', '', content, flags=re.DOTALL)
    # Remove HTML comments
    cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)
    # Remove script blocks
    cleaned = re.sub(r'<script[^>]*>.*?</script>', '', cleaned, flags=re.DOTALL)
    # Remove style blocks
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL)
    
    results = []
    for m in UNWRAPPED_HTML_RE.finditer(cleaned):
        text = m.group(2).strip()
        if text and CHINESE_RE.search(text):
            results.append(text)
    return results


def patch_file(filepath, dry_run=False):
    """Wrap unwrapped Chinese strings in a template file with <%: %> tags."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    changes = []
    new_content = content
    
    # Pattern: Chinese text between HTML tags, NOT inside <% %> blocks
    # Strategy: find Chinese text in HTML context and wrap with <%: %>
    
    # Find all positions of Chinese text runs in HTML
    # We need to be careful not to double-wrap already wrapped strings
    
    lines = content.split('\n')
    changes_made = 0
    
    for i, line in enumerate(lines):
        # Skip lines that are entirely inside a LuCI block
        if '<%' in line and line.strip().startswith('<%') and '%>' in line:
            continue
        
        # Find HTML text nodes with Chinese chars
        # Pattern: >Chinese text< but not ><%:Chinese%><
        # Also handle: alt="Chinese text"
        modified = line
        
        # Replace >text< patterns with Chinese that aren't already wrapped
        def replace_html_text(m):
            full = m.group(0)
            before = m.group(1)  # >
            text = m.group(2)
            after = m.group(3)   # <
            
            if not CHINESE_RE.search(text):
                return full
            
            # Don't wrap if it's inside <% %> or already wrapped
            if before.endswith('%>') or after.startswith('<%'):
                return full
            
            if not any(c.isascii() and c.isalpha() for c in text) or CHINESE_RE.search(text):
                # All Chinese or mixed - wrap it
                return f'{before}<%%:{text}%>{after}'
            
            return full
        
        modified = re.sub(r'(>)([^<]*?[\u4e00-\u9fff][^<]*?)(<)',
                         replace_html_text, modified)
        
        if modified != line:
            lines[i] = modified
            changes_made += 1
    
    if changes_made > 0 and not dry_run:
        # Backup
        backup = filepath + '.bak_template'
        if not os.path.exists(backup):
            with open(backup, 'w', encoding='utf-8') as f:
                f.write(content)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"  Patched {filepath}: {changes_made} changes")
    
    return changes_made


def scan_directory(directory):
    """Scan a directory of template files for unwrapped Chinese text."""
    results = {}
    for root, dirs, files in os.walk(directory):
        for fn in files:
            if fn.endswith('.htm') or fn.endswith('.html'):
                fpath = os.path.join(root, fn)
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                found = find_unwrapped_chinese(content)
                if found:
                    results[fpath] = found
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: template_patcher.py <scan|patch> <directory> [--wet]")
        print("  scan: list files with unwrapped Chinese text")
        print("  patch: wrap them with <%: %> tags")
        sys.exit(1)
    
    action = sys.argv[1]
    target = sys.argv[2]
    wet = '--wet' in sys.argv
    
    if action == 'scan':
        results = scan_directory(target)
        if not results:
            print("No unwrapped Chinese text found!")
            return
        
        total = 0
        for fpath, strings in sorted(results.items()):
            print(f"\n{fpath}:")
            for s in set(strings):
                print(f"  \"{s}\"")
                total += 1
        print(f"\nTotal: {total} unwrapped strings in {len(results)} files")
    
    elif action == 'patch':
        if not wet:
            print("DRY RUN - add --wet to actually modify files")
        results = scan_directory(target)
        if not results:
            print("No unwrapped Chinese text to patch!")
            return
        
        changes = 0
        for fpath in sorted(results.keys()):
            c = patch_file(fpath, dry_run=not wet)
            changes += c
        
        print(f"\nTotal changes: {changes}")
        if not wet:
            print("Add --wet to apply changes")


if __name__ == '__main__':
    main()
